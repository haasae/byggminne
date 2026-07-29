"""Tests for src.heating.graph_enrich."""
import json
from pathlib import Path

from rdflib import Graph, Namespace, RDF

from src.heating.graph_enrich import emit_building

BLDG = Namespace('urn:example#')
REC = Namespace('https://w3id.org/rec#')
BRICK = Namespace('https://brickschema.org/schema/1.4/Brick#')
HLAB = Namespace('urn:hlab#')

INDEX = {
    "building": "B90",
    "building_node": "B90_TestBuilding",
    "building_name": "TestBuilding",
    "zones": {
        "B90-MA-A-1-1": {
            "level_id": "B90-MA_F1",
            "level_label": "F1",
            "sub_building_id": "B90-MA",
            "sub_building_label": "MA",
        }
    },
}

DATA = {
    "zone_table": {
        ("B90", "B90-MA-A-1-1"): {"kind": "t_triple", "flags": ["dead_gain"]},
    },
    "regimes": {
        ("B90", "B90-MA-A-1-1"): {"regime": "binary"},
    },
    "heating_types": {
        ("B90", "B90-MA-A-1-1"): {
            "verdict": "electric-fast",
            "confidence": 0.8,
            "reasoning": "fast decay, binary",
        },
    },
    "step_summary": {
        ("B90", "B90-MA-A-1-1"): {
            "minutes_to_1k": {"median": 45, "iqr": 10},
        },
    },
    "orientation": {
        ("B90", "B90-MA-A-1-1"): {
            "orientation": "heating",
            "winter_duty": 60.0,
            "summer_duty": 5.0,
        },
    },
}


def _load_graph(tmp_path):
    out = tmp_path / "B90.ttl"
    emit_building("B90", INDEX, DATA, out)
    g = Graph()
    g.parse(str(out), format="turtle")
    return g


def test_graph_parses(tmp_path):
    g = _load_graph(tmp_path)
    assert len(g) > 0


def test_spatial_skeleton(tmp_path):
    g = _load_graph(tmp_path)
    assert (BLDG["B90"], RDF.type, REC.Site) in g
    assert (BLDG["B90_TestBuilding"], RDF.type, REC.Building) in g
    assert (BLDG["B90-MA"], RDF.type, REC.SubBuilding) in g
    assert (BLDG["B90-MA_F1"], RDF.type, REC.Level) in g
    assert (BLDG["B90-MA-A-1-1"], RDF.type, REC.Zone) in g


def test_bound_triple(tmp_path):
    g = _load_graph(tmp_path)
    assert (BLDG["B90-MA-A-1-1_sensor"], RDF.type, BRICK.Temperature_Sensor) in g
    assert (BLDG["B90-MA-A-1-1_setpoint"], RDF.type, BRICK.Temperature_Setpoint) in g
    assert (BLDG["B90-MA-A-1-1_actuator"], RDF.type, BRICK.Valve_Position_Command) in g


def test_derived_facts(tmp_path):
    g = _load_graph(tmp_path)
    z = BLDG["B90-MA-A-1-1"]
    heating_types = list(g.objects(z, HLAB.heatingType))
    assert len(heating_types) == 1
    assert str(heating_types[0]) == "electric-fast"

    regimes = list(g.objects(z, HLAB.gainRegime))
    assert str(regimes[0]) == "binary"

    tau = list(g.objects(z, HLAB.tauMedianMin))
    assert int(tau[0]) == 45

    flags = [str(o) for o in g.objects(z, HLAB.qualityFlag)]
    assert "dead_gain" in flags


def test_zone_without_index_gets_flag(tmp_path):
    """A zone missing from the index gets locationMissing=true."""
    data = {
        "zone_table": {("B90", "B90-MA-A-1-9"): {"kind": "t_triple", "flags": []}},
        "regimes": {}, "heating_types": {}, "step_summary": {}, "orientation": {},
    }
    index = {**INDEX, "zones": {}}  # empty index
    out = tmp_path / "B90_missing.ttl"
    emit_building("B90", index, data, out)
    g = Graph()
    g.parse(str(out), format="turtle")
    flags = list(g.objects(BLDG["B90-MA-A-1-9"], HLAB.locationMissing))
    assert flags and str(flags[0]).lower() == "true"
