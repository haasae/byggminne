"""Streaming per-zone statistics for the room-heating triple.

Welford / capped-distinct pattern lifted from src/profile/series_stats.py:
O(1) memory per zone, one pass, stdlib only. The accumulator is source-agnostic:
feed it (ts, actual, setpoint, gain) with None for missing fields.
"""
import math

SP_LEVELS_CAP = 64      # setpoints are schedule-stepped (2-6 levels expected)
GAIN_DISTINCT_CAP = 4096  # past this a gain is unambiguously modulating
GAIN_TOP_VALUES = 8     # exact-value histogram peaks kept for Phase 2
T_DISTINCT_CAP = 512    # stuck-sensor screen support


class _Welford:
    __slots__ = ("n", "mean", "_m2", "min", "max")

    def __init__(self):
        self.n = 0
        self.mean = 0.0
        self._m2 = 0.0
        self.min = None
        self.max = None

    def add(self, x):
        self.n += 1
        if self.min is None or x < self.min:
            self.min = x
        if self.max is None or x > self.max:
            self.max = x
        d = x - self.mean
        self.mean += d / self.n
        self._m2 += d * (x - self.mean)

    @property
    def std(self):
        return math.sqrt(self._m2 / (self.n - 1)) if self.n > 1 else 0.0

    def row(self):
        if self.n == 0:
            return {"n": 0}
        return {
            "n": self.n,
            "min": round(self.min, 4),
            "max": round(self.max, 4),
            "mean": round(self.mean, 4),
            "std": round(self.std, 4),
        }


class TripleAccumulator:
    """One zone's streaming stats. add() per grid row; row() at the end."""

    def __init__(self):
        self.n_grid = 0        # all rows on the padded grid
        self.n_data = 0        # rows with at least one non-empty field
        self.n_bad = 0         # rows whose values failed to parse
        self.first_ts = None   # first / last row with any data
        self.last_ts = None

        self.t = _Welford()
        self._t_distinct = set()
        self.t_distinct_capped = False
        self._t_last = None
        self.t_changes = 0

        self.sp = _Welford()
        self.sp_levels = {}    # value -> count, capped
        self.sp_levels_capped = False
        self._sp_last = None
        self.sp_steps = 0

        self.gain = _Welford()
        self.gain_at_0 = 0
        self.gain_at_100 = 0
        self.gain_interior = 0   # strictly between 0 and 100
        self._gain_values = {}   # value -> count, capped
        self.gain_values_capped = False

        self.comfort = _Welford()  # actual - setpoint, both present
        self.comfort_below_1 = 0   # dev < -1 K (too cold)
        self.comfort_above_1 = 0   # dev > +1 K (too warm)

    def add_empty(self):
        self.n_grid += 1

    def add(self, ts, actual, setpoint, gain):
        self.n_grid += 1
        self.n_data += 1
        if self.first_ts is None:
            self.first_ts = ts
        self.last_ts = ts

        if actual is not None:
            self.t.add(actual)
            if not self.t_distinct_capped:
                self._t_distinct.add(actual)
                if len(self._t_distinct) > T_DISTINCT_CAP:
                    self.t_distinct_capped = True
                    self._t_distinct.clear()
            if self._t_last is not None and actual != self._t_last:
                self.t_changes += 1
            self._t_last = actual

        if setpoint is not None:
            self.sp.add(setpoint)
            if not self.sp_levels_capped:
                self.sp_levels[setpoint] = self.sp_levels.get(setpoint, 0) + 1
                if len(self.sp_levels) > SP_LEVELS_CAP:
                    self.sp_levels_capped = True
                    self.sp_levels.clear()
            if self._sp_last is not None and setpoint != self._sp_last:
                self.sp_steps += 1
            self._sp_last = setpoint

        if gain is not None:
            self.gain.add(gain)
            if gain == 0.0:
                self.gain_at_0 += 1
            elif gain == 100.0:
                self.gain_at_100 += 1
            elif 0.0 < gain < 100.0:
                self.gain_interior += 1
            if not self.gain_values_capped:
                self._gain_values[gain] = self._gain_values.get(gain, 0) + 1
                if len(self._gain_values) > GAIN_DISTINCT_CAP:
                    self.gain_values_capped = True
                    self._gain_values.clear()

        if actual is not None and setpoint is not None:
            dev = actual - setpoint
            self.comfort.add(dev)
            if dev < -1.0:
                self.comfort_below_1 += 1
            elif dev > 1.0:
                self.comfort_above_1 += 1

    def row(self):
        gn = self.gain.n
        sp_levels = None
        if not self.sp_levels_capped:
            sp_levels = sorted(
                ({"value": v, "count": c} for v, c in self.sp_levels.items()),
                key=lambda e: -e["count"],
            )
        gain_top = None
        gain_distinct = None
        if not self.gain_values_capped:
            gain_distinct = len(self._gain_values)
            gain_top = sorted(
                ({"value": v, "count": c} for v, c in self._gain_values.items()),
                key=lambda e: -e["count"],
            )[:GAIN_TOP_VALUES]
        return {
            "n_grid": self.n_grid,
            "n_data": self.n_data,
            "n_bad": self.n_bad,
            "first_data_ts": self.first_ts,
            "last_data_ts": self.last_ts,
            "t": self.t.row() | {
                "distinct": None if self.t_distinct_capped else len(self._t_distinct),
                "changes": self.t_changes,
            },
            "sp": self.sp.row() | {
                "levels": sp_levels,  # None when capped (not schedule-stepped)
                "steps": self.sp_steps,
            },
            "gain": self.gain.row() | {
                "pct_at_0": round(self.gain_at_0 / gn, 4) if gn else None,
                "pct_at_100": round(self.gain_at_100 / gn, 4) if gn else None,
                "pct_interior": round(self.gain_interior / gn, 4) if gn else None,
                "distinct": gain_distinct,  # None when capped (modulating)
                "top_values": gain_top,
            },
            "comfort": self.comfort.row() | {
                "n_below_minus1": self.comfort_below_1,
                "n_above_plus1": self.comfort_above_1,
            },
        }
