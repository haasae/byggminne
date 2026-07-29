"""Adapter discovery + header dispatch on the mini fixture."""
from pathlib import Path

from src.heating.collectief_adapter import classify_header, discover

FIXTURE = Path(__file__).parent / "fixtures" / "collectief_mini"


def test_discover_finds_all_and_dispatches_on_header():
    files = list(discover(FIXTURE))
    assert len(files) == 8
    kinds = {f.zone: f.kind for f in files}
    assert kinds["B90-MA-A-1-1"] == "t_triple"
    assert kinds["B90-MA-A-1-5"] == "co2_triple"
    # The orphan trap: T-zone-style filename, COOL header -> NOT a t_triple.
    assert kinds["B90-MA-A-1-6"] == "cool_actual"
    assert kinds["B91-MA-A-1-1"] == "t_triple"


def test_buildings_filter():
    files = list(discover(FIXTURE, ["B91"]))
    assert [f.zone for f in files] == ["B91-MA-A-1-1"]
    assert all(f.building == "B91" for f in files)


def test_classify_header_edge_cases():
    assert classify_header(["Timestamp", "T_Actualvalue", "T_Setvalue", "T_Gain"]) == "t_triple"
    assert classify_header(["Timestamp", "VAV_Gain"]) == "vav_gain"
    assert classify_header(["Timestamp", "Whatever"]) == "other"
    assert classify_header(["NotTimestamp", "T_Gain"]) == "other"
    assert classify_header([]) == "other"
