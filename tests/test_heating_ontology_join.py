"""Tests for src.heating.ontology_join."""
from pathlib import Path

from src.heating.ontology_join import parse_building

FIXTURE = Path(__file__).parent / "fixtures" / "collectief_mini"
TTL = FIXTURE / "Buildings" / "B90" / "B90_ontology.ttl"


def test_parse_building_site_and_name():
    result = parse_building(TTL)
    assert result["building"] == "B90"
    assert result["building_name"] == "TestBuilding"
    assert result["building_node"] == "B90_TestBuilding"


def test_parse_building_zone_count():
    result = parse_building(TTL)
    assert len(result["zones"]) == 2
    assert "B90-MA-A-1-1" in result["zones"]
    assert "B90-MA-A-1-2" in result["zones"]


def test_parse_building_zone_location():
    result = parse_building(TTL)
    z = result["zones"]["B90-MA-A-1-1"]
    assert z["level_label"] == "F1"
    assert z["level_id"] == "B90-MA_F1"
    assert z["sub_building_label"] == "MA"
    assert z["sub_building_id"] == "B90-MA"


def test_parse_building_cli(tmp_path):
    from src.heating.ontology_join import main
    root = str(FIXTURE)
    ret = main(["--root", root, "--out-dir", str(tmp_path), "--buildings", "B90"])
    assert ret == 0
    out = tmp_path / "B90.json"
    assert out.exists()
    import json
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["building"] == "B90"
    assert len(data["zones"]) == 2
