"""Step-response miner on synthetic series with known time constant."""
import math

from src.common.io_utils import read_json
from pathlib import Path

from src.heating.step_response import (mine_events, outdoor_bin, season_of,
                                       summarize_zone)

RULES = read_json(Path(__file__).parents[1] / "knowledge_base" / "heating_rules.json")
SR = RULES["step_response"]

TAU_MIN = 120.0
T_AMBIENT = 15.0
T_WARM = 21.0


def _write_synthetic(path, gain_after_drop=0.0, days=3):
    """1-min grid; sp 21 -> 17 at 21:00, back to 21 at 05:00; exp decay."""
    lines = ["Timestamp,T_Actualvalue,T_Setvalue,T_Gain"]
    for day in range(10, 10 + days):
        decay_start = None
        for minute in range(1440):
            h = minute // 60
            night = h >= 21 or h < 5
            sp = 17.0 if night else 21.0
            if h >= 21:
                if decay_start is None:
                    decay_start = minute
                dt = minute - decay_start
                t = T_AMBIENT + (T_WARM - T_AMBIENT) * math.exp(-dt / TAU_MIN)
                gain = gain_after_drop
            elif h < 5:
                dt = minute + (1440 - 1260)  # decay continues past midnight
                t = T_AMBIENT + (T_WARM - T_AMBIENT) * math.exp(-dt / TAU_MIN)
                gain = gain_after_drop
            else:
                t, gain = T_WARM, 100.0
            lines.append(f"2023-01-{day:02d} {h:02d}:{minute % 60:02d}:00+00:00,"
                         f"{t:.3f},{sp},{gain}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_decay_metrics_match_physics(tmp_path):
    p = tmp_path / "z.csv"
    _write_synthetic(p)
    events = [e for e in mine_events(p, SR) if not e["reheat_interrupt"]]
    assert len(events) >= 2  # one setback per evening (last may hit EOF)
    e = events[0]
    # T(t) = 15 + 6*exp(-t/120): drops 1K at t = 120*ln(6/5) ~ 21.9 min.
    assert e["minutes_to_1k"] is not None and 18 <= e["minutes_to_1k"] <= 26
    # t63 of a first-order decay ~ tau (plateau truncation biases slightly low).
    assert e["t63_minutes"] is not None and 95 <= e["t63_minutes"] <= 135
    assert e["slope_first_hour_k_per_h"] < -1.0  # initially ~ -3 K/h
    assert e["season"] == "2022-23"


def test_no_free_decay_when_heater_stays_on(tmp_path):
    p = tmp_path / "z.csv"
    _write_synthetic(p, gain_after_drop=100.0)
    assert mine_events(p, SR) == []  # heater on -> not a decay experiment


def test_season_and_outdoor_bin():
    assert season_of("2023-01-15") == "2022-23"
    assert season_of("2023-09-01") == "2023-24"
    edges = SR["outdoor_bins_c"]
    assert outdoor_bin(-7.0, edges) == "<-5"
    assert outdoor_bin(2.0, edges) == "<5"
    assert outdoor_bin(11.0, edges) == ">=10"
    assert outdoor_bin(None, edges) is None


def test_summarize_zone_quartiles_and_no_drop_share():
    events = [
        {"ts": f"2023-01-{d:02d} 21:00:00+00:00", "minutes_to_1k": m,
         "slope_first_hour_k_per_h": -2.0, "t63_minutes": None,
         "window_min": 480, "reheat_interrupt": False,
         "season": "2022-23"}
        for d, m in [(10, 20), (11, 24), (12, 22), (13, 30), (14, None)]
    ]
    weather = {f"2023-01-{d:02d}": -3.0 for d in range(10, 15)}
    row = summarize_zone("B90", "Z", events, weather, SR)
    assert row["n_events"] == 5
    assert row["minutes_to_1k"]["n"] == 4
    assert 20 <= row["minutes_to_1k"]["median"] <= 25
    assert row["no_1k_drop_share"] == 0.2  # 1 of 5 long windows never dropped
    assert row["by_season"]["2022-23"]["n"] == 4
    assert row["by_outdoor_bin"]["<0"]["n"] == 4
