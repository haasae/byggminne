import pytest

from src.profile.seasonal_check import (
    load_series,
    monthly_profile,
    pearson,
    resolve_reference,
)


def test_monthly_profile_groups_by_month():
    points = {
        "2025-01-01 00:00:00.000": -2.0,
        "2025-01-15 00:00:00.000": -4.0,
        "2025-07-01 00:00:00.000": 18.0,
        "2025-07-15 00:00:00.000": 22.0,
    }
    profile = monthly_profile(points)
    assert profile["01"] == (-3.0, 2, -4.0, -2.0)
    assert profile["07"] == (20.0, 2, 18.0, 22.0)


def test_pearson_signs_and_alignment():
    # y = -x (perfect anti-correlation); z = x (perfect correlation).
    ts = [f"2025-01-01 0{i}:00:00.000" for i in range(6)]
    x = {t: float(i) for i, t in enumerate(ts)}
    y = {t: -float(i) for i, t in enumerate(ts)}
    z = dict(x)
    z["2025-12-31 00:00:00.000"] = 99.0  # extra unaligned sample is ignored
    r_neg, n = pearson(x, y)
    assert n == 6 and abs(r_neg + 1.0) < 1e-9
    r_pos, n = pearson(x, z)
    assert n == 6 and abs(r_pos - 1.0) < 1e-9


def test_pearson_undefined_for_constant_series():
    ts = [f"2025-01-01 0{i}:00:00.000" for i in range(4)]
    x = {t: float(i) for i, t in enumerate(ts)}
    const = {t: 7.0 for t in ts}
    r, n = pearson(x, const)
    assert r is None and n == 4
    assert pearson(x, {})[1] == 0


def test_resolve_reference_unique_and_ambiguous():
    labels = ["A/OU001-RT401.#85", "A/OU002-RT401.#85", "A/OU001-RT404.#85"]
    assert resolve_reference(labels, "OU001-RT401") == "A/OU001-RT401.#85"
    with pytest.raises(SystemExit):
        resolve_reference(labels, "RT401")   # two matches
    with pytest.raises(SystemExit):
        resolve_reference(labels, "nope")    # zero matches


def test_load_series_filters_and_parses(tmp_path):
    f = tmp_path / "x.csv"
    f.write_text(
        "KEEP,2025-01-01 00:00:00.000,1.5\n"
        "SKIP,2025-01-01 00:00:00.000,9\n"
        "KEEP,2025-01-01 00:10:00.000,bad\n"      # unparseable -> dropped
        "KEEP,2025-01-01 00:20:00.000,2.5\n",
        encoding="utf-8-sig",
    )
    series = load_series([f], {"KEEP"})
    assert set(series) == {"KEEP"}
    assert series["KEEP"] == {
        "2025-01-01 00:00:00.000": 1.5,
        "2025-01-01 00:20:00.000": 2.5,
    }
