from src.brick.readiness_report import assess, render_markdown

TYPED_ANCHORED = ("A20-P2-APP019:20053404-OU001/FCB.Local Application."
                  "Drenspumpe_P1.-P1_Drift.#85")
UNTYPED_LOOSE = "A20-P2-APP019:NIE00108D0A91DD/ModbusRTU2.floating point.#85"


def _rows():
    return [
        {"raw_label": TYPED_ANCHORED, "source_type": "bacnet",
         "function": "status", "measurement_type": "status", "unit": None,
         "primary_system": {"code": "3200", "description": "Varme"},
         "location": {"building": "20053404", "zone": None}, "confidence": 0.65},
        {"raw_label": UNTYPED_LOOSE, "source_type": "bacnet",
         "function": None, "measurement_type": None, "unit": None,
         "primary_system": None, "location": None, "confidence": 0.4},
    ]


def test_headline_percentages():
    m = assess(_rows())
    assert m["n_rows"] == 2
    assert m["pct_typed_beyond_point"] == 50.0
    assert m["pct_equipment_anchored"] == 50.0      # pump group vs bare token
    assert m["pct_with_building"] == 50.0
    assert m["pct_with_system"] == 50.0
    assert m["brick_class_counts"] == {"Status": 1, "Point": 1}


def test_gap_table_names_the_worst_family():
    m = assess(_rows())
    worst_sig = next(iter(m["families"]))
    assert "floating point" in worst_sig
    assert m["families"][worst_sig]["untyped"] == 1


def test_markdown_renders():
    md = render_markdown(assess(_rows()), "outputs.jsonl")
    assert "decoded well enough" in md
    assert "brick:Status" in md
    assert "Fix-next queue" in md
