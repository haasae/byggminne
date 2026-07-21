from rdflib import Graph, Literal, Namespace, RDF, RDFS

from src.brick.emit_graph import build_graphs, sanitize
from src.brick.mapping import BRICK

BRICK_NS = Namespace(BRICK)

# Two buildings, one equipment group (2 pump points on 20053404), one
# system-token row, one unplaced row, one æøå label, one unknown/untyped row.
PUMP_A = ("A20-P2-APP019:20053404-OU001/FCB.Local Application."
          "Drenspumpe_P1.-P1_Drift.#85")
PUMP_B = ("A20-P2-APP019:20053404-OU001/FCB.Local Application."
          "Drenspumpe_P1.-P1_Alarm_Høy_vannstand.#85")
SYSTEM_ROW = "A20-P2-APP019:NIE00108D0A91DD/N2 Trunk 1.320001.Analoge innganger.RT401.#85"
UNPLACED = "A20-P2-APP019:NIE00108D0A91DD/ModbusRTU2.floating point.#85"


def _row(raw_label, building, **over):
    row = {
        "raw_label": raw_label, "source_type": "bacnet",
        "function": "status", "measurement_type": "status",
        "unit": None, "primary_system": None, "component": None,
        "location": {"building": building, "zone": None} if building else None,
        "confidence": 0.6, "validated": False,
    }
    row.update(over)
    return row


ROWS = [
    _row(PUMP_A, "20053404"),
    _row(PUMP_B, "20053404", function="alarm"),
    _row(SYSTEM_ROW, "bygg3", function="temperatur",
         measurement_type="temperatur", unit="°C",
         primary_system={"code": "3200", "description": "Varmeanlegg"}),
    _row(UNPLACED, None, function=None, measurement_type=None),
    _row("bad row", None, schema_invalid=True),
]


def _emit(tmp_path):
    graphs, meta = build_graphs(ROWS, "tasen")
    out = {}
    for stem, g in graphs.items():
        path = tmp_path / f"{stem}.ttl"
        g.serialize(destination=str(path), format="turtle")
        reparsed = Graph()
        reparsed.parse(str(path), format="turtle")   # parse error = test failure
        out[stem] = reparsed
    return out, meta


def test_one_graph_per_building_plus_site_file(tmp_path):
    graphs, meta = _emit(tmp_path)
    assert set(graphs) == {"tasen_20053404", "tasen_bygg3", "tasen_site"}
    assert meta["rows_skipped_schema_invalid"] == 1
    assert meta["files"]["tasen_20053404"]["points"] == 2


def test_points_typed_and_anchored_to_equipment(tmp_path):
    graphs, _ = _emit(tmp_path)
    g = graphs["tasen_20053404"]
    ex = Namespace("https://example.org/label-decoder/tasen#")

    pumps = list(g.subjects(RDF.type, BRICK_NS.Pump))
    assert len(pumps) == 1                          # one equipment node, 2 points
    points = list(g.subjects(BRICK_NS.isPointOf, pumps[0]))
    assert len(points) == 2
    assert (pumps[0], BRICK_NS.hasLocation,
            ex["building_20053404"]) in g

    statuses = set(g.subjects(RDF.type, BRICK_NS.Status))
    alarms = set(g.subjects(RDF.type, BRICK_NS.Alarm))
    assert len(statuses) == 1 and len(alarms) == 1


def test_raw_label_survives_verbatim_utf8(tmp_path):
    graphs, _ = _emit(tmp_path)
    labels = {str(o) for o in graphs["tasen_20053404"].objects(None, RDFS.label)}
    assert PUMP_B in labels                          # æøå intact after re-parse


def test_system_membership_needs_structural_token(tmp_path):
    graphs, _ = _emit(tmp_path)
    g = graphs["tasen_bygg3"]
    ex = Namespace("https://example.org/label-decoder/tasen#")
    system = ex["system_320001"]
    assert (system, RDF.type, BRICK_NS.Hot_Water_System) in g
    points = list(g.objects(system, BRICK_NS.hasPoint))
    assert len(points) == 1
    assert (points[0], RDF.type, BRICK_NS.Temperature_Sensor) in g
    units = list(g.objects(points[0], BRICK_NS.hasUnit))
    assert [str(u) for u in units] == ["http://qudt.org/vocab/unit/DEG_C"]


def test_unplaced_untyped_row_lands_in_site_file_as_plain_point(tmp_path):
    graphs, _ = _emit(tmp_path)
    g = graphs["tasen_site"]
    ex = Namespace("https://example.org/label-decoder/tasen#")
    site = ex["site_tasen"]
    assert (site, RDF.type, BRICK_NS.Site) in g
    points = list(g.subjects(BRICK_NS.isPointOf, site))
    assert len(points) == 1
    assert (points[0], RDF.type, BRICK_NS.Point) in g   # fallback class only
    assert (None, RDF.type, BRICK_NS.Building) not in g


def test_sanitize_is_ascii_and_collision_safe():
    assert sanitize("20053404") == "20053404"
    a, b = sanitize("Høy vannstand"), sanitize("Hoy vannstand")
    assert a != b                                    # hash suffix disambiguates
    assert all(c.isascii() for c in a)
