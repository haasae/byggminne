import json

import pytest

from src.decode.decode_label import decode_one, extract_json
from src.decode.runner import DecodeRunner
from src.validate.schema_validator import build_validator

# ---------------------------------------------------------------------------
# extract_json
# ---------------------------------------------------------------------------

def test_plain_object():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_object_wrapped_in_prose_and_fences():
    text = 'Sure! Here is the decode:\n```json\n{"a": 1, "b": null}\n```\nDone.'
    assert extract_json(text) == {"a": 1, "b": None}


def test_braces_inside_strings_do_not_confuse_matching():
    obj = {"reasoning": "code {434.003} per NS", "x": "}{"}
    assert extract_json(json.dumps(obj)) == obj


def test_escaped_quotes_inside_strings():
    text = '{"a": "he said \\"hi\\" and left {"}'
    assert extract_json(text) == {"a": 'he said "hi" and left {'}


def test_nested_objects():
    obj = {"primary_system": {"code": "3200", "description": "varme"}}
    assert extract_json("noise " + json.dumps(obj) + " noise") == obj


def test_first_balanced_object_wins():
    assert extract_json('{"first": 1} and then {"second": 2}') == {"first": 1}


def test_no_json_raises():
    with pytest.raises(ValueError):
        extract_json("no object here")


def test_truncated_object_raises():
    with pytest.raises(ValueError):
        extract_json('{"a": {"b": 1}')  # never closes the outer brace


def test_balanced_but_malformed_raises_valueerror_family():
    # decode_one catches (ValueError, json.JSONDecodeError); JSONDecodeError
    # is a ValueError subclass, so this stays inside the retry loop.
    with pytest.raises(ValueError):
        extract_json("{a: 1}")


# ---------------------------------------------------------------------------
# decode_one
# ---------------------------------------------------------------------------

VALID = json.dumps({
    "raw_label": "L1", "source_type": "kiona", "confidence": 0.8, "validated": False,
})
INVALID_SCHEMA = json.dumps({  # missing required raw_label
    "source_type": "kiona", "confidence": 0.8, "validated": False,
})


class ScriptedRunner(DecodeRunner):
    """Replays canned responses and records every prompt it was given."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.responses.pop(0)


@pytest.fixture(scope="module")
def validator():
    return build_validator()


def _decode(responses, validator, max_retries=2):
    runner = ScriptedRunner(responses)
    result = decode_one("L1", "kiona", "CONTEXT", runner, validator, max_retries)
    return result, runner


def test_valid_first_try(validator):
    result, runner = _decode([VALID], validator)
    assert result["valid"] is True
    assert result["attempts"] == 1
    assert result["instance"]["raw_label"] == "L1"
    # The one prompt carries the context and the label, and is not a retry.
    assert "CONTEXT" in runner.prompts[0]
    assert "raw_label: L1" in runner.prompts[0]
    assert "REJECTED" not in runner.prompts[0]


def test_unparseable_then_valid_retries_fresh(validator):
    result, runner = _decode(["not json at all", VALID], validator)
    assert result["valid"] is True
    assert result["attempts"] == 2
    assert "THE PREVIOUS OUTPUT WAS REJECTED" in runner.prompts[1]
    assert "not a single valid JSON object" in runner.prompts[1]


def test_schema_invalid_then_valid_carries_validator_complaint(validator):
    result, runner = _decode([INVALID_SCHEMA, VALID], validator)
    assert result["valid"] is True
    assert result["attempts"] == 2
    assert "raw_label" in runner.prompts[1]  # the complaint names the missing field


def test_retry_prompt_is_rebuilt_not_accumulated(validator):
    # Two failures then success: the third prompt must contain exactly ONE
    # rejection block (rebuilt from the base prompt), not a growing history.
    result, runner = _decode(["garbage", INVALID_SCHEMA, VALID], validator)
    assert result["valid"] is True
    assert result["attempts"] == 3
    assert runner.prompts[2].count("THE PREVIOUS OUTPUT WAS REJECTED") == 1


def test_exhausted_retries_reports_failure_with_raw(validator):
    result, runner = _decode(["junk", "more junk", "still junk"], validator)
    assert result["valid"] is False
    assert result["instance"] is None
    assert result["attempts"] == 3          # max_retries=2 -> 3 calls
    assert result["raw"] == "still junk"    # last raw text kept for the audit trail
    assert len(runner.prompts) == 3


def test_zero_retries_gives_single_attempt(validator):
    result, runner = _decode(["junk"], validator, max_retries=0)
    assert result["valid"] is False
    assert result["attempts"] == 1
    assert len(runner.prompts) == 1
