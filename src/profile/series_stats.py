"""Data-profiling layer, step 1: streaming per-label statistics.

One pass over raw `label,timestamp,value` CSVs (no header, UTF-8, decimal
points, globally time-sorted rows -- verified against data/raw/tasen). Emits one
JSON line of cheap statistics per label; src/profile/cross_check.py then tests
decode guesses against them (CLAUDE.md section 4: name = hypothesis, data = test).

Everything is O(1) memory per label (Welford for mean/std, a capped set for
distinct values), so multi-GB files stream in minutes with stdlib only.
Timestamps are compared as strings: the format is fixed-width and zero-padded
('2025-01-01 00:00:00.000'), so lexicographic order == chronological order.

    python -m src.profile.series_stats "data/raw/tasen/*.csv" \
        -o runs/profile/tasen/stats.jsonl [--labels labels.txt] [--progress]
"""
import argparse
import glob
import math
import re
import sys
from pathlib import Path

from src.common.io_utils import configure_stdout_utf8, write_jsonl

# 'AV punkter' / 'BV punkter' in a file name reveal the export's BACnet family
# (analog vs binary values) -- a free cross-check signal for object_type.
_FILE_KIND = re.compile(r"\b(AV|BV)\s+punkter\b", re.IGNORECASE)

DISTINCT_CAP = 32     # past this many distinct values a series is clearly analog
VALUES_LISTED_MAX = 8  # list the exact values only for small (status-like) sets


class SeriesStats:
    """Streaming accumulator for one label's series."""

    __slots__ = (
        "n_rows", "n_bad_values", "files", "file_kinds",
        "first_ts", "last_ts", "n_out_of_order",
        "n_num", "min", "max", "_mean", "_m2", "n_zero", "n_negative",
        "distinct", "distinct_capped", "n_decreases", "_last_ts", "_last_value",
    )

    def __init__(self):
        self.n_rows = 0
        self.n_bad_values = 0
        self.files = set()
        self.file_kinds = set()
        self.first_ts = None
        self.last_ts = None
        self.n_out_of_order = 0
        self.n_num = 0
        self.min = None
        self.max = None
        self._mean = 0.0
        self._m2 = 0.0
        self.n_zero = 0
        self.n_negative = 0
        self.distinct = set()
        self.distinct_capped = False
        self.n_decreases = 0
        self._last_ts = None
        self._last_value = None

    def add(self, ts, value_text, file_name, file_kind):
        self.n_rows += 1
        self.files.add(file_name)
        if file_kind:
            self.file_kinds.add(file_kind)

        if self.first_ts is None or ts < self.first_ts:
            self.first_ts = ts
        if self.last_ts is None or ts > self.last_ts:
            self.last_ts = ts

        try:
            value = float(value_text)
        except ValueError:
            self.n_bad_values += 1
            return
        if math.isnan(value):
            self.n_bad_values += 1
            return

        self.n_num += 1
        if self.min is None or value < self.min:
            self.min = value
        if self.max is None or value > self.max:
            self.max = value
        # Welford's online mean/variance.
        delta = value - self._mean
        self._mean += delta / self.n_num
        self._m2 += delta * (value - self._mean)
        if value == 0:
            self.n_zero += 1
        if value < 0:
            self.n_negative += 1

        if not self.distinct_capped:
            self.distinct.add(value)
            if len(self.distinct) > DISTINCT_CAP:
                self.distinct_capped = True
                self.distinct.clear()  # release memory; count is now unknown

        # Monotonicity relies on per-label chronological order. A row that goes
        # backwards in time is counted (n_out_of_order) and skipped as a stray
        # rather than corrupting the decrease count.
        if self._last_ts is not None and ts < self._last_ts:
            self.n_out_of_order += 1
            return
        if self._last_value is not None and value < self._last_value:
            self.n_decreases += 1
        self._last_ts = ts
        self._last_value = value

    def to_row(self, label):
        distinct_count = None if self.distinct_capped else len(self.distinct)
        std = math.sqrt(self._m2 / (self.n_num - 1)) if self.n_num > 1 else 0.0
        return {
            "raw_label": label,
            "n_rows": self.n_rows,
            "n_bad_values": self.n_bad_values,
            "files": sorted(self.files),
            "file_kinds": sorted(self.file_kinds),
            "first_ts": self.first_ts,
            "last_ts": self.last_ts,
            "n_out_of_order": self.n_out_of_order,
            "n_num": self.n_num,
            "min": self.min,
            "max": self.max,
            "mean": self._mean if self.n_num else None,
            "std": std if self.n_num else None,
            "zero_fraction": (self.n_zero / self.n_num) if self.n_num else None,
            "n_negative": self.n_negative,
            "distinct_count": distinct_count,
            "distinct_capped": self.distinct_capped,
            "values": (sorted(self.distinct)
                       if distinct_count is not None and distinct_count <= VALUES_LISTED_MAX
                       else None),
            "is_binary": (distinct_count is not None
                          and 0 < distinct_count <= 2),
            "monotonic_nondecreasing": (self.n_decreases == 0) if self.n_num > 1 else None,
            "n_decreases": self.n_decreases,
        }


def file_kind(file_name):
    """'AV' / 'BV' from an '... AV punkter ...' file name, else None."""
    m = _FILE_KIND.search(file_name)
    return m.group(1).upper() if m else None


def profile_files(paths, labels=None, progress=False):
    """Stream every path once; return {label: SeriesStats}.

    `labels`: optional set restricting which labels are accumulated.
    Returns (stats_by_label, n_malformed_lines).
    """
    stats = {}
    n_malformed = 0
    n_lines = 0
    for path in paths:
        path = Path(path)
        kind = file_kind(path.name)
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            for line in fh:
                n_lines += 1
                if progress and n_lines % 5_000_000 == 0:
                    print(f"  ... {n_lines:,} lines", file=sys.stderr)
                line = line.rstrip("\r\n")
                if not line:
                    continue
                parts = line.rsplit(",", 2)
                if len(parts) != 3:
                    n_malformed += 1
                    continue
                label, ts, value_text = parts[0], parts[1].strip(), parts[2].strip()
                if labels is not None and label not in labels:
                    continue
                st = stats.get(label)
                if st is None:
                    st = stats[label] = SeriesStats()
                st.add(ts, value_text, path.name, kind)
    return stats, n_malformed


def _resolve(patterns):
    """File paths or glob patterns -> sorted matching paths (as in src/extract)."""
    paths = []
    for pattern in patterns:
        matched = sorted(glob.glob(pattern))
        paths.extend(Path(p) for p in (matched if matched else [pattern]))
    return paths


def main() -> int:
    configure_stdout_utf8()
    ap = argparse.ArgumentParser(
        description="Stream label,timestamp,value CSVs and emit per-label statistics."
    )
    ap.add_argument("inputs", nargs="+", help="CSV files or glob patterns")
    ap.add_argument("-o", "--output", required=True, help="output stats.jsonl")
    ap.add_argument("--labels", help="optional text file; restrict to these labels")
    ap.add_argument("--progress", action="store_true",
                    help="print a progress line every 5M input lines (stderr)")
    args = ap.parse_args()

    label_filter = None
    if args.labels:
        label_filter = {
            line.strip() for line in
            Path(args.labels).read_text(encoding="utf-8").splitlines()
            if line.strip()
        }

    paths = _resolve(args.inputs)
    stats, n_malformed = profile_files(paths, labels=label_filter, progress=args.progress)

    rows = [stats[label].to_row(label) for label in sorted(stats)]
    write_jsonl(args.output, rows)
    print(f"{len(rows)} labels from {len(paths)} file(s) "
          f"({n_malformed} malformed line(s) skipped) -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
