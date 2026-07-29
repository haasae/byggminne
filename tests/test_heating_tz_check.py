"""tz_check step mining on synthetic series with a known schedule."""
from src.heating.tz_check import collect_up_steps, top_modes


def _write_zone(path, up_minute):
    """Two weeks of 10-min rows; setpoint rises 17->21 at up_minute daily."""
    lines = ["Timestamp,T_Actualvalue,T_Setvalue,T_Gain"]
    for day in range(10, 24):
        for minute in range(0, 1440, 10):
            sp = 21.0 if minute >= up_minute else 17.0
            lines.append(f"2023-01-{day:02d} {minute//60:02d}:{minute%60:02d}:00+00:00,20.0,{sp},0.0")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_up_steps_found_at_schedule_time(tmp_path):
    p = tmp_path / "zone.csv"
    _write_zone(p, up_minute=300)  # 05:00
    steps = collect_up_steps(p, "2023-01-10", "2023-01-23")
    assert len(steps) == 14  # one up-step per day, 14 days in window
    mode, count = top_modes(steps, 1)[0]
    assert mode == 300
    assert count == 14


def test_date_window_respected(tmp_path):
    p = tmp_path / "zone.csv"
    _write_zone(p, up_minute=300)
    steps = collect_up_steps(p, "2023-01-15", "2023-01-16")
    assert len(steps) == 2  # one per day in the 2-day window
