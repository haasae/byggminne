"""End-to-end zone table on the mini fixture: flags, cache, survey check."""
import json
from pathlib import Path

from src.common.io_utils import read_json
from src.heating.build_zone_table import build, check_survey

FIXTURE = Path(__file__).parent / "fixtures" / "collectief_mini"
RULES = read_json(Path(__file__).parents[1] / "knowledge_base" / "heating_rules.json")


def run(tmp_path, buildings=None):
    return build(FIXTURE, buildings, tmp_path / "table.jsonl",
                 tmp_path / "cache.jsonl", RULES)


def test_flags_on_fixture(tmp_path):
    rows = {r["zone"]: r for r in run(tmp_path)}
    assert len(rows) == 8
    assert rows["B90-MA-A-1-1"]["flags"] == []           # healthy binary zone
    assert "dead_gain" in rows["B90-MA-A-1-3"]["flags"]  # gain always 0
    assert "empty" in rows["B90-MA-A-1-4"]["flags"]      # no data at all
    assert "stuck_sensor_suspect" in rows["B90-MA-A-1-7"]["flags"]  # constant T
    # Binary zone stats sane: gain overwhelmingly at 0/100, 2 sp levels.
    g = rows["B90-MA-A-1-1"]["stats"]["gain"]
    assert g["pct_at_0"] + g["pct_at_100"] > 0.99
    assert len(rows["B90-MA-A-1-1"]["stats"]["sp"]["levels"]) == 2
    # Modulating zone: large interior mass.
    assert rows["B90-MA-A-1-2"]["stats"]["gain"]["pct_interior"] > 0.9


def test_scan_cache_hits_on_second_run(tmp_path, capsys):
    run(tmp_path)
    capsys.readouterr()
    run(tmp_path)
    out = capsys.readouterr().out
    assert "(8 cached)" in out


def test_empty_grid_rows_counted(tmp_path):
    rows = {r["zone"]: r for r in run(tmp_path)}
    s = rows["B90-MA-A-1-1"]["stats"]
    assert s["n_grid"] > s["n_data"] > 0  # fixture sprinkles empty rows


def test_check_survey_logic():
    def zrow(building, zone, kind="t_triple", flags=()):
        return {"building": building, "zone": zone, "kind": kind,
                "flags": list(flags)}
    # Correct B07: 32 t_triples incl. the two dead ones.
    good = [zrow("B07", f"B07-MA-A-1-{i}", flags=(
        ["dead_gain"] if i in (12, 13) else [])) for i in range(1, 33)]
    assert check_survey(good) == []
    # Wrong count -> error; missing dead flag -> error.
    assert any("t_triples" in e for e in check_survey(good[:-1]))
    bad = [dict(r, flags=[]) for r in good]
    assert any("dead_gain" in e for e in check_survey(bad))
    # Buildings absent from the table are not checked.
    assert check_survey([zrow("B02", f"B02-Z-{i}") for i in range(18)]) == []
