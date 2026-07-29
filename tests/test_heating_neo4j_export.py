"""Tests for src.heating.neo4j_export."""
import json
from pathlib import Path

from src.heating.neo4j_export import generate_cypher

FIXTURE = Path(__file__).parent / "fixtures" / "collectief_mini"


def _make_index(tmp_path):
    """Write a minimal index JSON for B90."""
    idx = {
        "building": "B90",
        "building_node": "B90_TestBuilding",
        "building_name": "TestBuilding",
        "zones": {
            "B90-MA-A-1-1": {
                "level_id": "B90-MA_F1", "level_label": "F1",
                "sub_building_id": "B90-MA", "sub_building_label": "MA",
            }
        },
    }
    index_dir = tmp_path / "index"
    index_dir.mkdir()
    (index_dir / "B90.json").write_text(
        json.dumps(idx), encoding="utf-8")
    return index_dir


def _make_runs(tmp_path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    (runs_dir / "zone_table.jsonl").write_text(
        '{"building":"B90","zone":"B90-MA-A-1-1","kind":"t_triple","flags":[]}\n',
        encoding="utf-8")
    (runs_dir / "regimes.jsonl").write_text(
        '{"building":"B90","zone":"B90-MA-A-1-1","regime":"binary"}\n',
        encoding="utf-8")
    (runs_dir / "heating_types.jsonl").write_text(
        '{"building":"B90","zone":"B90-MA-A-1-1","verdict":"electric-fast",'
        '"confidence":0.9,"reasoning":"fast"}\n', encoding="utf-8")
    (runs_dir / "step_summary.jsonl").write_text(
        '{"building":"B90","zone":"B90-MA-A-1-1",'
        '"minutes_to_1k":{"median":45,"iqr":5}}\n', encoding="utf-8")
    (runs_dir / "orientation.jsonl").write_text(
        '{"building":"B90","zone":"B90-MA-A-1-1",'
        '"orientation":"heating","winter_duty":65.0,"summer_duty":4.0}\n',
        encoding="utf-8")
    return runs_dir


def test_cypher_contains_constraints(tmp_path):
    cypher = generate_cypher(_make_index(tmp_path), _make_runs(tmp_path))
    assert "CREATE CONSTRAINT zone_id" in cypher
    assert "CREATE CONSTRAINT site_id" in cypher


def test_cypher_spatial_skeleton(tmp_path):
    cypher = generate_cypher(_make_index(tmp_path), _make_runs(tmp_path))
    assert "MERGE (n:Site {id: 'B90'})" in cypher
    assert "MERGE (n:Building {id: 'B90_TestBuilding'})" in cypher
    assert "MERGE (n:SubBuilding {id: 'B90-MA'})" in cypher
    assert "MERGE (n:Level {id: 'B90-MA_F1'})" in cypher


def test_cypher_zone_properties(tmp_path):
    cypher = generate_cypher(_make_index(tmp_path), _make_runs(tmp_path))
    assert "MERGE (z:Zone {id: 'B90-MA-A-1-1'})" in cypher
    assert "heatingType = 'electric-fast'" in cypher
    assert "regime = 'binary'" in cypher
    assert "tauMedianMin = 45" in cypher
    assert "winterDutyPct = 65.0" in cypher


def test_cypher_location_relationship(tmp_path):
    cypher = generate_cypher(_make_index(tmp_path), _make_runs(tmp_path))
    assert "MERGE (z)-[:LOCATED_IN]->(l)" in cypher
    assert "B90-MA-A-1-1" in cypher
    assert "B90-MA_F1" in cypher


def _make_sk_index(tmp_path):
    """Index with known sub-buildings but no zone-level placement (Skøyen)."""
    idx = {
        "building": "SK",
        "building_node": "SK_Skoyen",
        "building_name": "Skoyen skole",
        "sub_buildings": [
            {"id": "SK-SKOLEBYGG", "name": "Skolebygg"},
            {"id": "SK-IDRETTSHALL", "name": "Idrettshall"},
        ],
        "zones": {"SK-360001": {"building_node": "SK_Skoyen"}},
    }
    index_dir = tmp_path / "index"
    index_dir.mkdir()
    (index_dir / "SK.json").write_text(json.dumps(idx), encoding="utf-8")
    return index_dir


def _make_sk_runs(tmp_path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    (runs_dir / "zone_table.jsonl").write_text(
        '{"building":"SK","zone":"SK-360001","kind":"t_triple","flags":[]}\n',
        encoding="utf-8")
    for name in ("regimes.jsonl", "heating_types.jsonl",
                 "step_summary.jsonl", "orientation.jsonl"):
        (runs_dir / name).write_text("", encoding="utf-8")
    return runs_dir


def test_cypher_known_sub_buildings(tmp_path):
    cypher = generate_cypher(_make_sk_index(tmp_path), _make_sk_runs(tmp_path))
    assert ("MERGE (n:SubBuilding {id: 'SK-SKOLEBYGG'}) "
            "SET n.name = 'Skolebygg'") in cypher
    assert ("MERGE (n:SubBuilding {id: 'SK-IDRETTSHALL'}) "
            "SET n.name = 'Idrettshall'") in cypher
    assert ("MATCH (a:SubBuilding {id:'SK-SKOLEBYGG'}), "
            "(b:Building {id:'SK_Skoyen'}) MERGE (a)-[:PART_OF]->(b);") in cypher


def test_cypher_zone_building_fallback(tmp_path):
    cypher = generate_cypher(_make_sk_index(tmp_path), _make_sk_runs(tmp_path))
    assert ("MATCH (z:Zone {id:'SK-360001'}), (b:Building {id:'SK_Skoyen'}) "
            "MERGE (z)-[:LOCATED_IN]->(b);") in cypher
    assert "WARNING: no location index for SK-360001" not in cypher


def test_cypher_meter_hierarchy(tmp_path):
    """Meters from the index become :Meter nodes; parent refs become
    SUBMETER_OF; root meters attach to the Building via METERS."""
    index_dir = _make_sk_index(tmp_path)
    idx = json.loads((index_dir / "SK.json").read_text(encoding="utf-8"))
    idx["meters"] = [
        {"id": "000000000001", "name": "Fjernvarme hovedmaaler",
         "utility": "district_heating"},
        {"id": "000000000002,00000001", "name": "Varme 360.01",
         "parent": "000000000001", "utility": "district_heating"},
    ]
    (index_dir / "SK.json").write_text(json.dumps(idx), encoding="utf-8")
    cypher = generate_cypher(index_dir, _make_sk_runs(tmp_path))

    assert "CREATE CONSTRAINT meter_id" in cypher
    assert ("MERGE (m:Meter {id: '000000000001'}) "
            "SET m.name = 'Fjernvarme hovedmaaler', m.kind = 'main', "
            "m.utility = 'district_heating'") in cypher
    assert "m.kind = 'sub'" in cypher
    assert ("MATCH (a:Meter {id:'000000000002,00000001'}), "
            "(b:Meter {id:'000000000001'}) MERGE (a)-[:SUBMETER_OF]->(b);") in cypher
    assert ("MATCH (m:Meter {id:'000000000001'}), (b:Building {id:'SK_Skoyen'}) "
            "MERGE (m)-[:METERS]->(b);") in cypher


def test_cypher_systems_and_rooms(tmp_path):
    """systems/rooms index entries become :System / :Room nodes with points."""
    index_dir = _make_sk_index(tmp_path)
    idx = json.loads((index_dir / "SK.json").read_text(encoding="utf-8"))
    idx["systems"] = [
        {"id": "TA-320.001", "kind": "heating", "name": "Varmeanlegg 320.001",
         "points": [{"code": "RT401", "label": "raw1", "file": "f.csv"}]},
        {"id": "TA-320.001-BYGG5", "kind": "heating",
         "parent": "TA-320.001", "serves": "SK-SKOLEBYGG", "points": []},
        {"id": "TA-IK001-TEST", "kind": "device", "name": "Kjølemaskin IK001",
         "sub_building_id": "SK-SKOLEBYGG", "points": []},
        {"id": "TA-AHU1", "kind": "ahu", "controller": "C1",
         "subsystem": "360.001", "points": []},
    ]
    idx["rooms"] = [
        {"id": "TA-ROOM-3104-55", "number": "3104", "bygg": 3, "floor": 1,
         "bus": "ModbusRTU2", "address": 55, "sub_building_id": "TA-BYGG3",
         "points": [{"signal": "heating", "label": "raw2", "file": "g.csv"}]},
    ]
    (index_dir / "SK.json").write_text(json.dumps(idx), encoding="utf-8")
    cypher = generate_cypher(index_dir, _make_sk_runs(tmp_path))

    assert "CREATE CONSTRAINT system_id" in cypher
    assert "MERGE (s:System {id: 'TA-320.001'})" in cypher
    assert "s.name = 'Varmeanlegg 320.001'" in cypher
    assert ("MATCH (a:System {id:'TA-320.001-BYGG5'}), "
            "(b:System {id:'TA-320.001'}) MERGE (a)-[:PART_OF]->(b);") in cypher
    # 'serves' from the branch label -> SERVES the named sub-building
    assert ("MATCH (a:System {id:'TA-320.001-BYGG5'}), "
            "(b:SubBuilding {id:'SK-SKOLEBYGG'}) "
            "MERGE (a)-[:SERVES]->(b);") in cypher
    # data-backed placement -> LOCATED_IN the sub-building, not the Building
    assert ("MATCH (a:System {id:'TA-IK001-TEST'}), "
            "(b:SubBuilding {id:'SK-SKOLEBYGG'}) "
            "MERGE (a)-[:LOCATED_IN]->(b);") in cypher
    # a parentless, unplaced AHU is grouped under the Ventilasjon category
    assert "MERGE (s:System {id: 'SK_Skoyen-VENTILASJON'})" in cypher
    assert ("MATCH (a:System {id:'TA-AHU1'}), "
            "(b:System {id:'SK_Skoyen-VENTILASJON'}) "
            "MERGE (a)-[:PART_OF]->(b);") in cypher
    # every node carries a plain-language description
    assert "s.description = " in cypher
    assert "p.description = 'Temperaturgiver, tilluft/tur (RT401).'" in cypher
    assert "MERGE (p:Point {id: 'TA-320.001_RT401'})" in cypher
    assert "MERGE (r:Room {id: 'TA-ROOM-3104-55'})" in cypher
    assert "r.bygg = 3" in cypher
    # TA-BYGG3 is not a known sub-building in this index -> building fallback
    assert ("MATCH (r:Room {id:'TA-ROOM-3104-55'}), "
            "(b:Building {id:'SK_Skoyen'}) MERGE (r)-[:LOCATED_IN]->(b);") in cypher
    assert "MERGE (p:Point {id: 'TA-ROOM-3104-55_heating'})" in cypher


def test_cypher_zone_meter_link(tmp_path):
    index_dir = _make_sk_index(tmp_path)
    idx = json.loads((index_dir / "SK.json").read_text(encoding="utf-8"))
    idx["zones"]["SK-360001"]["meter_id"] = "000000000002,00000001"
    (index_dir / "SK.json").write_text(json.dumps(idx), encoding="utf-8")
    cypher = generate_cypher(index_dir, _make_sk_runs(tmp_path))
    assert ("MATCH (z:Zone {id:'SK-360001'}), "
            "(m:Meter {id:'000000000002,00000001'}) "
            "MERGE (z)-[:MEASURED_BY]->(m);") in cypher


def test_cypher_human_readability(tmp_path):
    """display_name -> Site/Building names; rooms get 'Rom N' names, triple
    booleans, floor Levels; points get Norwegian names."""
    index_dir = _make_sk_index(tmp_path)
    idx = json.loads((index_dir / "SK.json").read_text(encoding="utf-8"))
    idx["display_name"] = "Skøyen skole"
    idx["sub_buildings"][0]["heating"] = "radiator"
    idx["rooms"] = [
        {"id": "SK-ROOM-1-07", "number": "1-07", "plan": 1,
         "sub_building_id": "SK-SKOLEBYGG", "triple": True,
         "points": [
             {"signal": "temperature", "label": "raw-y", "file": "f.csv",
              "name": "Rom 1-07 Temp RT601"},
             {"signal": "temperature_setpoint", "label": "raw-r", "file": "f.csv"},
             {"signal": "heating", "label": "raw-u", "file": "f.csv"},
         ]},
        {"id": "SK-ROOM-2-01", "number": "2-01", "plan": 2,
         "sub_building_id": "SK-SKOLEBYGG", "triple": False,
         "points": [{"signal": "co2", "label": "raw-c", "file": "f.csv"}]},
        {"id": "SK-ROOM-U-01", "number": "U-01", "plan": 0,
         "sub_building_id": "SK-SKOLEBYGG", "points": []},
    ]
    (index_dir / "SK.json").write_text(
        json.dumps(idx, ensure_ascii=False), encoding="utf-8")
    cypher = generate_cypher(index_dir, _make_sk_runs(tmp_path))

    # 1+2: site and building carry the real Norwegian name
    assert "MERGE (n:Site {id: 'SK'}) SET n.name = 'Skøyen skole'" in cypher
    assert "MERGE (n:Building {id: 'SK_Skoyen'}) SET n.name = 'Skøyen skole'" in cypher
    # 3: rooms are named "Rom <number>"
    assert "r.name = 'Rom 1-07'" in cypher
    # 4: the triple spelled out on the room node
    assert ("r.hasTemperature = true, r.hasSetpoint = true, "
            "r.hasHeating = true") in cypher
    assert ("r.hasTemperature = false, r.hasSetpoint = false, "
            "r.hasHeating = false") in cypher
    # 5: floor grouping Room -> Level -> SubBuilding
    assert ("MERGE (n:Level {id: 'SK-SKOLEBYGG-PLAN1'}) "
            "SET n.label = 'Plan 1'") in cypher
    # floor 0 renders as U1 (underetasje), matching the BMS schedule naming
    assert ("MERGE (n:Level {id: 'SK-SKOLEBYGG-PLAN0'}) "
            "SET n.label = 'U1'") in cypher
    assert ("MATCH (a:Level {id:'SK-SKOLEBYGG-PLAN1'}), "
            "(b:SubBuilding {id:'SK-SKOLEBYGG'}) MERGE (a)-[:PART_OF]->(b);") in cypher
    assert ("MATCH (r:Room {id:'SK-ROOM-1-07'}), "
            "(l:Level {id:'SK-SKOLEBYGG-PLAN1'}) "
            "MERGE (r)-[:LOCATED_IN]->(l);") in cypher
    # heating type on the sub-building, inherited by its rooms
    assert "n.heatingType = 'radiator'" in cypher
    assert "r.heatingType = 'radiator'" in cypher
    # point names: BMS name kept, missing ones built from the signal
    assert "p.name = 'Rom 1-07 Temp RT601'" in cypher
    assert "p.name = 'Rom 1-07 Settpunkt temperatur'" in cypher
    assert "p.name = 'Rom 1-07 Varmepådrag'" in cypher


def test_cypher_provenance(tmp_path):
    """Hand-curated facts carry source/confidence onto edges and nodes;
    rooms inheriting heatingType without room-level evidence get 'assumed'."""
    index_dir = _make_sk_index(tmp_path)
    idx = json.loads((index_dir / "SK.json").read_text(encoding="utf-8"))
    idx["sub_buildings"][0]["heating"] = "radiator"
    idx["systems"] = [
        {"id": "SK-320.001", "kind": "heating", "name": "Varmeanlegg",
         "sub_building_id": "SK-SKOLEBYGG", "serves": ["SK-IDRETTSHALL"],
         "points": []},
    ]
    idx["rooms"] = [
        {"id": "SK-ROOM-320x-81", "number": "3208", "plan": 1,
         "sub_building_id": "SK-SKOLEBYGG", "points": []},
        {"id": "SK-ROOM-H13", "number": "H13", "plan": 1,
         "sub_building_id": "SK-SKOLEBYGG", "points": []},
    ]
    idx["provenance"] = {
        "SK-ROOM-H13": {
            "heating": {"value": "gulvvarme", "source": "kurssiden F",
                        "confidence": "verified"},
        },
        "SK-320.001": {
            "location": {"source": "UI-panel A", "confidence": "verified"},
            "serves": {"source": "kursnavn B", "confidence": "curated"},
        },
        "SK-SKOLEBYGG": {
            "heating": {"source": "romside C", "confidence": "curated",
                        "conflict": True},
        },
        "SK-ROOM-320x-81": {
            "number": {"source": "verdimatch D", "confidence": "verified"},
        },
        "SK-360001": {
            "location": {"source": "dekningsomraade E", "confidence": "verified"},
        },
    }
    (index_dir / "SK.json").write_text(
        json.dumps(idx, ensure_ascii=False), encoding="utf-8")
    cypher = generate_cypher(index_dir, _make_sk_runs(tmp_path))

    # placement + serves edges carry the provenance as edge properties
    assert ("MERGE (a)-[r:LOCATED_IN]->(b) "
            "SET r.source = 'UI-panel A', r.confidence = 'verified';") in cypher
    assert ("MERGE (a)-[r:SERVES]->(b) "
            "SET r.source = 'kursnavn B', r.confidence = 'curated';") in cypher
    # sub-building heating fact -> node properties
    assert "n.heatingSource = 'romside C'" in cypher
    assert "n.heatingConfidence = 'curated'" in cypher
    # a flagged conflict is visible in the description, not only on click
    assert "n.heatingConflict = true" in cypher
    assert "NB: kildene er i konflikt om varmetypen" in cypher
    # resolved room number keeps its evidence
    assert "r.numberSource = 'verdimatch D'" in cypher
    assert "r.numberConfidence = 'verified'" in cypher
    # inherited heating type is honestly stamped 'assumed'
    assert "r.heatingSource = 'Arvet fra bygget (SK-SKOLEBYGG).'" in cypher
    assert "r.heatingConfidence = 'assumed'" in cypher
    # a room-level 'value' overrides the inherited type (mixed buildings)
    assert ("r.heatingType = 'gulvvarme', r.heatingSource = 'kurssiden F', "
            "r.heatingConfidence = 'verified'") in cypher
    # zone placement edge (building fallback branch) carries it too
    assert ("MERGE (z)-[r:LOCATED_IN]->(b) "
            "SET r.source = 'dekningsomraade E', "
            "r.confidence = 'verified';") in cypher
    # edges without provenance keep the old un-stamped shape
    assert "MERGE (a)-[:PART_OF]->(b);" in cypher


def test_cypher_point_nodes(tmp_path):
    cypher = generate_cypher(_make_index(tmp_path), _make_runs(tmp_path))
    assert "CREATE CONSTRAINT point_id" in cypher
    assert "MERGE (p:Point:Setpoint {id: 'B90-MA-A-1-1_setpoint'})" in cypher
    assert "MERGE (p:Point:Sensor {id: 'B90-MA-A-1-1_sensor'})" in cypher
    assert "MERGE (p:Point:Actuator {id: 'B90-MA-A-1-1_actuator'})" in cypher
    assert "p.column = 'T_Setvalue'" in cypher
    assert "p.file = 'Buildings/B90/Thermal zone/B90-MA-A-1-1.csv'" in cypher
    assert "MERGE (z)-[:HAS_POINT]->(p)" in cypher
