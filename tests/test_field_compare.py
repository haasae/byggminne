from src.common.fields import get_value, spec_for
from src.score.field_compare import (
    CORRECT,
    OVER_FILL,
    UNDER_FILL,
    WRONG_VALUE,
    compare_field,
)


def _cmp(path, pred_value, gold_value):
    spec = spec_for(path)
    # Build instances that place the value at the (possibly nested) path.
    def place(value):
        if "." in path:
            head, tail = path.split(".", 1)
            return {head: {tail: value}}
        return {path: value}
    return compare_field(spec, place(pred_value), place(gold_value))


def test_null_equals_null_is_correct():
    r = _cmp("carrier", None, None)
    assert r.verdict == CORRECT
    assert r.gold_nonnull is False


def test_under_fill_when_pred_null():
    r = _cmp("carrier", None, "el")
    assert r.verdict == UNDER_FILL
    assert r.gold_nonnull is True


def test_over_fill_when_gold_null():
    r = _cmp("component", "RT", None)
    assert r.verdict == OVER_FILL


def test_wrong_value_enum():
    r = _cmp("carrier", "el", "fjernvarme")
    assert r.verdict == WRONG_VALUE


def test_free_text_normalized_match():
    r = _cmp("function", "Temperatur", "temperatur")
    assert r.verdict == CORRECT


def test_code_prefix_match_is_correct_but_not_exact():
    r = _cmp("primary_system.code", "3600", "360")
    assert r.verdict == CORRECT
    assert r.exact is False


def test_code_exact_match():
    r = _cmp("primary_system.code", "3200", "3200")
    assert r.verdict == CORRECT
    assert r.exact is True


def test_code_prefix_mismatch_is_wrong():
    r = _cmp("primary_system.code", "370", "320")
    assert r.verdict == WRONG_VALUE
    assert r.exact is False


def test_get_value_nested_null():
    assert get_value({"location": {"building": None}}, "location.building") is None
    assert get_value({"location": {"building": "B1"}}, "location.building") == "B1"
    assert get_value({}, "location.zone") is None
