"""Heating-type verdicts: every class + the prior-conflict flag."""
from pathlib import Path

from src.common.io_utils import read_json
from src.heating.heating_type import classify

HT = read_json(Path(__file__).parents[1] / "knowledge_base" / "heating_rules.json")["heating_type"]


def reg(building, regime="binary"):
    return {"building": building, "zone": "Z", "regime": regime}


def step(median, n_events=30, no_drop=0.0):
    return {"n_events": n_events,
            "minutes_to_1k": None if median is None else
            {"n": n_events, "median": median, "iqr": 10},
            "no_1k_drop_share": no_drop}


def test_electric_fast_with_matching_prior():
    r = classify(reg("B07"), step(25), HT)
    assert r["verdict"] == "electric-fast" and r["confidence"] == 0.9


def test_fast_zone_in_hydronic_building_is_flagged():
    r = classify(reg("B01"), step(25), HT)
    assert r["verdict"] == "electric-fast"
    assert r["confidence"] == 0.55 and "CONFLICTS" in r["reasoning"]


def test_hydronic_slow():
    r = classify(reg("B02", "modulating"), step(300), HT)
    assert r["verdict"] == "hydronic-slow" and r["confidence"] == 0.75


def test_floor_slow_when_windows_never_drop():
    r = classify(reg("B04"), step(None, no_drop=0.7), HT)
    assert r["verdict"] == "floor-slow"


def test_ambiguous_middle_and_insufficient_events():
    assert classify(reg("B03"), step(150), HT)["verdict"] == "ambiguous"
    assert classify(reg("B03"), step(25, n_events=3), HT)["verdict"] == "ambiguous"
    assert classify(reg("B03"), None, HT)["verdict"] == "ambiguous"


def test_dead_zone_excluded():
    r = classify(reg("B07", "dead"), None, HT)
    assert r["verdict"] == "excluded" and r["confidence"] == 1.0
