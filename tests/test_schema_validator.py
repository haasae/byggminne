from src.common.io_utils import repo_root
from src.validate.schema_validator import build_validator, validate_file, validate_instance


def test_examples_are_schema_valid():
    validator = build_validator()
    examples = sorted((repo_root() / "examples").glob("*.json"))
    assert examples, "expected worked examples in examples/"
    for path in examples:
        assert validate_file(path, validator) == [], f"{path.name} should be valid"


def test_missing_required_field_reports_error():
    validator = build_validator()
    instance = {"source_type": "kiona", "confidence": 0.5, "validated": False}  # no raw_label
    errors = validate_instance(instance, validator)
    assert errors
    assert any("raw_label" in msg for _, msg in errors)


def test_bad_enum_reports_error():
    validator = build_validator()
    instance = {
        "raw_label": "x", "source_type": "kiona", "confidence": 0.5, "validated": False,
        "carrier": "not-a-carrier",
    }
    errors = validate_instance(instance, validator)
    assert errors


def test_all_unknown_fields_null_is_valid():
    """The prompt says "set unknown fields to null" -- the schema must accept a
    decode that follows that instruction for every optional field (the
    null-contradiction regression)."""
    validator = build_validator()
    instance = {
        "raw_label": "x", "source_type": "other", "confidence": 0.1, "validated": False,
        "carrier": None, "function": None, "measurement_type": None, "unit": None,
        "object_type": None, "primary_system": None, "subsystem": None,
        "component": None, "location": None, "is_derived": None,
        "reasoning": None, "data_checks": None, "relationships": [],
    }
    assert validate_instance(instance, validator) == []


def test_partially_known_location_is_valid():
    validator = build_validator()
    instance = {
        "raw_label": "x", "source_type": "kiona", "confidence": 0.5, "validated": False,
        "location": {"building": "B1", "zone": None},
    }
    assert validate_instance(instance, validator) == []


def test_null_relationships_still_rejected():
    """relationships stays an array by contract (the prompt says empty array,
    never null) -- downstream consumers may iterate it unconditionally."""
    validator = build_validator()
    instance = {
        "raw_label": "x", "source_type": "kiona", "confidence": 0.5, "validated": False,
        "relationships": None,
    }
    assert validate_instance(instance, validator)
