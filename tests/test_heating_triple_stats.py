"""TripleAccumulator: verified against hand-computed values."""
import statistics

from src.heating.triple_stats import TripleAccumulator


def test_binary_gain_and_setpoint_levels():
    acc = TripleAccumulator()
    # 8 rows: gain 0 x4, 100 x3, 50 x1 (interior); sp 17 x4 then 21 x4 (1 step).
    seq = [(17.0, 0.0)] * 4 + [(21.0, 100.0)] * 3 + [(21.0, 50.0)]
    for i, (sp, gain) in enumerate(seq):
        acc.add(f"2023-01-10 00:{i:02d}:00+00:00", 20.0, sp, gain)
    acc.add_empty()
    row = acc.row()
    assert row["n_grid"] == 9 and row["n_data"] == 8
    assert row["gain"]["pct_at_0"] == 0.5
    assert row["gain"]["pct_at_100"] == 0.375
    assert row["gain"]["pct_interior"] == 0.125
    assert row["gain"]["distinct"] == 3
    levels = {e["value"]: e["count"] for e in row["sp"]["levels"]}
    assert levels == {17.0: 4, 21.0: 4}
    assert row["sp"]["steps"] == 1


def test_welford_matches_statistics_module():
    acc = TripleAccumulator()
    values = [19.5, 20.1, 20.7, 21.3, 20.9, 19.8]
    for i, v in enumerate(values):
        acc.add(f"2023-01-10 01:{i:02d}:00+00:00", v, None, None)
    row = acc.row()
    # row() rounds to 4 decimals
    assert abs(row["t"]["mean"] - statistics.fmean(values)) < 1e-4
    assert abs(row["t"]["std"] - statistics.stdev(values)) < 1e-4
    assert row["t"]["min"] == 19.5 and row["t"]["max"] == 21.3


def test_comfort_deviation_counts():
    acc = TripleAccumulator()
    # devs: -2 (below), 0, +1.5 (above), -0.5
    for i, (a, sp) in enumerate([(19.0, 21.0), (21.0, 21.0), (22.5, 21.0), (20.5, 21.0)]):
        acc.add(f"2023-01-10 02:{i:02d}:00+00:00", a, sp, None)
    row = acc.row()
    assert row["comfort"]["n"] == 4
    assert row["comfort"]["n_below_minus1"] == 1
    assert row["comfort"]["n_above_plus1"] == 1
    assert abs(row["comfort"]["mean"] - (-0.25)) < 1e-9


def test_empty_accumulator():
    row = TripleAccumulator().row()
    assert row["n_grid"] == 0 and row["n_data"] == 0
    assert row["t"]["n"] == 0 and row["gain"]["pct_at_0"] is None
