from src.common.readiness import (
    GAP_BUILDING,
    GAP_LOW_CONFIDENCE,
    GAP_POINT_SEMANTICS,
    GAP_PRIMARY_SYSTEM,
    readiness_gaps,
)


def _row(**over):
    row = {
        "raw_label": "x", "source_type": "bacnet",
        "primary_system": {"code": "3200", "description": "Varme"},
        "measurement_type": "temperatur", "function": "temperatur",
        "location": {"building": "20053401", "zone": None},
        "confidence": 0.65,
    }
    row.update(over)
    return row


def test_complete_row_has_no_gaps():
    assert readiness_gaps(_row()) == ()


def test_each_gap_fires():
    assert readiness_gaps(_row(primary_system=None)) == (GAP_PRIMARY_SYSTEM,)
    assert readiness_gaps(_row(location=None)) == (GAP_BUILDING,)
    assert readiness_gaps(_row(location={"building": None, "zone": "R1"})) == (GAP_BUILDING,)
    assert readiness_gaps(_row(confidence=0.4)) == (GAP_LOW_CONFIDENCE,)


def test_point_semantics_needs_both_null():
    assert readiness_gaps(_row(measurement_type=None)) == ()
    assert readiness_gaps(_row(function=None)) == ()
    assert readiness_gaps(_row(measurement_type=None, function=None)) == (
        GAP_POINT_SEMANTICS,)


def test_gaps_accumulate():
    gaps = readiness_gaps({"raw_label": "x", "source_type": "other"})
    assert set(gaps) == {GAP_PRIMARY_SYSTEM, GAP_POINT_SEMANTICS,
                         GAP_BUILDING, GAP_LOW_CONFIDENCE}
