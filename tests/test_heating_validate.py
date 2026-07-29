"""Validation channels: pinned, priors, physics sign, reader quirks."""
from pathlib import Path

from src.common.io_utils import read_json
from src.heating.collectief_adapter import (_norm_date, read_meter_daily,
                                            read_weather_daily)
from src.heating.validate_regimes import (check_physics, check_pinned,
                                          check_priors)

FIXTURE = Path(__file__).parent / "fixtures" / "collectief_mini"
RULES = read_json(Path(__file__).parents[1] / "knowledge_base" / "heating_rules.json")


def reg(building, zone, regime):
    return {"building": building, "zone": zone, "regime": regime, "flags": []}


def test_pinned_pass_and_fail():
    rows = [reg("B01", "B01-MA-A-1-21", "modulating"),
            reg("B07", "B07-MA-A-1-12", "dead"),
            reg("B07", "B07-MA-A-1-13", "dead")]
    assert check_pinned(rows) == []  # B06/B04 absent -> their pins skipped
    rows[0]["regime"] = "binary"
    assert any("B01-MA-A-1-21" in e for e in check_pinned(rows))


def test_pinned_b04_needs_both_regimes():
    rows = [reg("B04", f"Z{i}", "binary") for i in range(5)]
    assert any("B04" in e for e in check_pinned(rows))
    rows.append(reg("B04", "Z9", "modulating"))
    assert check_pinned(rows) == []


def test_priors_warn_only_on_majority_flip():
    rows = [reg("B07", f"Z{i}", "binary") for i in range(9)]
    rows.append(reg("B07", "Z9", "modulating"))
    assert check_priors(rows) == []
    flipped = [reg("B07", f"Z{i}", "modulating") for i in range(9)]
    warns = check_priors(flipped)
    assert len(warns) == 1 and "finding" in warns[0]


def test_physics_sign(tmp_path):
    # 40 heating-season days: duty falls as temp rises -> r < 0 -> no errors.
    proxy = tmp_path / "B90.csv"
    lines = ["zone,hour_utc,mean_gain,n"]
    weather = {}
    for i in range(40):
        date = f"2023-01-{i + 1:02d}" if i < 31 else f"2023-02-{i - 30:02d}"
        temp = -5.0 + i * 0.3
        weather[date] = temp
        lines.append(f"Z1,{date} 00,{80 - i * 1.5:.1f},6")
    proxy.write_text("\n".join(lines) + "\n", encoding="utf-8")
    errors, detail = check_physics(["B90"], tmp_path, weather, RULES)
    assert errors == [] and "r=-" in detail[0]
    # Flip the relationship -> hard failure.
    lines = ["zone,hour_utc,mean_gain,n"] + [
        f"Z1,{d} 00,{20 + weather[d] * 2:.1f},6" for d in weather]
    proxy.write_text("\n".join(lines) + "\n", encoding="utf-8")
    errors, _ = check_physics(["B90"], tmp_path, weather, RULES)
    assert any("POSITIVELY" in e for e in errors)


def test_norm_date_formats():
    assert _norm_date("2022-08-31 22:00:00") == "2022-08-31"
    assert _norm_date("31/08/2022 22:00") == "2022-08-31"
    assert _norm_date("bogus") is None


def test_meter_reader_quirks():
    # B90: ISO + named column.
    days = read_meter_daily(FIXTURE, "B90")
    assert abs(days["2023-01-10"] - sum(10 + h % 5 for h in range(24))) < 1e-9
    # B91: DD/MM/YYYY + unnamed time column + empty early values.
    days = read_meter_daily(FIXTURE, "B91")
    assert days == {"2023-01-10": 10.0}


def test_weather_reader_skips_sentinels():
    daily = read_weather_daily(FIXTURE)
    assert "2023-01-13" not in daily  # only row that day is -999
    assert abs(daily["2023-01-10"] - (3.0 + 6 / 24)) < 1e-9  # base -2+5=3, +1 for 6h
