from src.decode.merge_outputs import merge, merge_row

LABEL = "SITE:111-OU001/-XQ401.#1"


def _det(**over):
    row = {
        "raw_label": LABEL, "source_type": "bacnet",
        "carrier": None, "function": None, "measurement_type": None,
        "unit": None, "object_type": None,
        "primary_system": {"code": "3200", "description": "Varme"},
        "subsystem": None, "component": None,
        "location": {"building": "111", "zone": None},
        "is_derived": None, "confidence": 0.4,
        "reasoning": "controller segment -> building 111",
        "data_checks": None, "relationships": [], "validated": False,
        "decode_method": "rules", "decoded_kb_version": None,
    }
    row.update(over)
    return row


def _llm(**over):
    row = _det(
        function="temperatur", measurement_type="temperatur",
        location={"building": "111", "zone": "Rom 1-03"},
        confidence=0.7, reasoning="llm reasoning",
        decode_method="llm", decoded_kb_version="abc123def456",
    )
    row.update(over)
    return row


def test_llm_fills_nulls_and_notes_it():
    merged, adopted, conflicts = merge_row(_det(), _llm())
    assert merged["measurement_type"] == "temperatur"
    assert merged["location"] == {"building": "111", "zone": "Rom 1-03"}
    assert "location.zone" in adopted and "function" in adopted
    assert conflicts == []
    assert "from llm enrichment (kb abc123def456)" in merged["reasoning"]
    assert merged["reasoning"].startswith("controller segment")  # det kept
    assert merged["decode_method"] == "rules+llm"
    assert merged["validated"] is False


def test_deterministic_nonnull_wins_and_conflict_is_logged():
    det = _det(measurement_type="trykk")
    merged, _, conflicts = merge_row(det, _llm())
    assert merged["measurement_type"] == "trykk"
    assert conflicts == [{"field": "measurement_type",
                          "deterministic": "trykk", "llm": "temperatur"}]


def test_confidence_formula():
    merged, _, _ = merge_row(_det(confidence=0.4), _llm(confidence=0.7))
    assert merged["confidence"] == 0.6                     # max(0.4, 0.7-0.1)
    merged, _, _ = merge_row(_det(confidence=0.85), _llm(confidence=0.7))
    assert merged["confidence"] == 0.85                    # det floor holds
    merged, _, _ = merge_row(_det(confidence=0.4), _llm(confidence=1.0))
    assert merged["confidence"] == 0.9                     # capped


def test_no_adoption_leaves_row_untouched():
    det = _det()
    llm = _llm(function=None, measurement_type=None, location=None)
    merged, adopted, _ = merge_row(det, llm)
    assert adopted == []
    assert merged == det


def test_merge_skips_invalid_and_unknown_llm_rows():
    det_rows = [_det()]
    llm_rows = [
        _llm(raw_label="never seen"),                       # unknown label
        {"raw_label": LABEL, "schema_invalid": True},       # skill gave up
    ]
    merged, conflicts, stats = merge(det_rows, llm_rows)
    assert merged == det_rows                               # nothing adopted
    assert stats["llm_unknown_label"] == 1
    assert stats["llm_schema_invalid"] == 1
    assert stats["rows_enriched"] == 0
    assert conflicts == []


def test_merge_end_to_end_schema_valid():
    merged, conflicts, stats = merge([_det()], [_llm()])
    assert stats["rows_enriched"] == 1
    assert merged[0]["decode_method"] == "rules+llm"        # enum accepts it
    assert conflicts == []
