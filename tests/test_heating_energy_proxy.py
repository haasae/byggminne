"""Energy proxy: hourly means, resumability, daily weighted aggregation."""
from pathlib import Path

from src.heating.energy_proxy import build_proxy, hourly_means, read_daily_duty

FIXTURE = Path(__file__).parent / "fixtures" / "collectief_mini"
ZONE1 = FIXTURE / "Buildings" / "B90" / "Thermal zone" / "B90-MA-A-1-1.csv"


def test_hourly_means_match_fixture_schedule():
    # Fixture: gain 100 during 05-09 and 17-21 local schedule, else 0.
    by_hour = {h: (m, n) for h, m, n in hourly_means(ZONE1)}
    assert by_hour["2023-01-10 06"][0] == 100.0
    assert by_hour["2023-01-10 12"][0] == 0.0
    # 10-min sampling -> max 6 samples/hour; empties reduce n, never the mean.
    assert 1 <= by_hour["2023-01-10 06"][1] <= 6


def test_build_proxy_and_resume(tmp_path, capsys):
    build_proxy(FIXTURE, ["B90"], tmp_path)
    out = capsys.readouterr().out
    assert "+5 zones" in out  # all 5 t_triples scanned
    build_proxy(FIXTURE, ["B90"], tmp_path)
    out = capsys.readouterr().out
    # ponytail: an all-empty zone emits no rows, so it re-scans every run
    # (one such file in the fleet); the 4 with data are resumed from disk.
    assert "(4 already present)" in out
    csv = tmp_path / "B90.csv"
    assert csv.exists()
    header = csv.read_text(encoding="utf-8").splitlines()[0]
    assert header == "zone,hour_utc,mean_gain,n"


def test_zone_orientation_classes(tmp_path):
    from src.common.io_utils import read_json
    from src.heating.energy_proxy import zone_orientation
    rules = read_json(Path(__file__).parents[1] / "knowledge_base" /
                      "heating_rules.json")["orientation"]
    p = tmp_path / "B.csv"
    p.write_text(
        "zone,hour_utc,mean_gain,n\n"
        "HEAT,2023-01-10 00,80.0,6\nHEAT,2023-07-10 00,5.0,6\n"
        "COOL,2023-01-10 00,7.9,6\nCOOL,2023-07-10 00,90.0,6\n"
        "DUAL,2023-01-10 00,30.0,6\nDUAL,2023-07-10 00,28.0,6\n"
        "IDLE,2023-01-10 00,0.0,6\nIDLE,2023-07-10 00,1.0,6\n",
        encoding="utf-8",
    )
    o = zone_orientation(p, rules)
    # Winter-dominant heating still allowed a cold-summer-morning trickle.
    assert o["HEAT"]["orientation"] == "heating"
    # Summer-DOMINANT gain = mislabeled cooling actuator (the B04 signature).
    assert o["COOL"]["orientation"] == "cooling"
    # Active both seasons, neither dominant -> dual (fan-coil both ways).
    assert o["DUAL"]["orientation"] == "dual"
    assert o["IDLE"]["orientation"] == "idle"
    assert o["COOL"]["summer_duty"] == 90.0


def test_read_daily_duty_include_filter(tmp_path):
    p = tmp_path / "B.csv"
    p.write_text("zone,hour_utc,mean_gain,n\n"
                 "Z1,2023-01-10 00,100.0,6\nZ2,2023-01-10 00,0.0,6\n",
                 encoding="utf-8")
    from src.heating.energy_proxy import read_daily_duty as rdd
    assert rdd(p, {"Z1"})["2023-01-10"] == 100.0
    assert rdd(p)["2023-01-10"] == 50.0


def test_orientation_out_flag(tmp_path):
    import json
    from src.heating.energy_proxy import main
    out_dir = tmp_path / "proxy"
    orient = tmp_path / "orientation.jsonl"
    rules = Path(__file__).parents[1] / "knowledge_base" / "heating_rules.json"
    main(["--root", str(FIXTURE), "--buildings", "B90",
          "--out-dir", str(out_dir), "--orientation-out", str(orient),
          "--rules", str(rules)])
    rows = [json.loads(l) for l in orient.read_text(encoding="utf-8").splitlines()]
    assert rows, "orientation.jsonl is empty"
    assert set(rows[0]) == {"building", "zone", "orientation",
                            "winter_duty", "summer_duty"}
    assert all(r["building"] == "B90" for r in rows)


def test_read_daily_duty_weighted(tmp_path):
    p = tmp_path / "B.csv"
    p.write_text(
        "zone,hour_utc,mean_gain,n\n"
        "Z1,2023-01-10 00,100.0,6\n"
        "Z1,2023-01-10 01,0.0,2\n"
        "Z2,2023-01-10 00,50.0,4\n",
        encoding="utf-8",
    )
    duty = read_daily_duty(p)
    # (100*6 + 0*2 + 50*4) / 12 = 800/12
    assert abs(duty["2023-01-10"] - 800 / 12) < 1e-9
