"""Single-label manual-test command: decode one label, get instance + verdict.

Hermetic: uses its own tmp validated store; the repo KB store is never read.
"""
from src.common.io_utils import write_jsonl
from src.decode.try_label import render, try_label

LABEL = "TEST-BYGG-01:111-OU001/-RT401.#1"


def _stored_instance():
    return {
        "raw_label": LABEL,
        "source_type": "bacnet",
        "carrier": None,
        "function": "temperatur",
        "measurement_type": "temperatur",
        "unit": None,
        "object_type": None,
        "primary_system": {"code": "3200", "description": "Varme"},
        "subsystem": None,
        "component": "RT401 (RT = Temperaturgiver)",
        "location": {"building": "111", "zone": None},
        "is_derived": False,
        "confidence": 0.9,
        "reasoning": "test fixture",
        "data_checks": None,
        "relationships": [],
        "validated": True,
    }


def test_try_label_exact_store_hit(tmp_path):
    store = tmp_path / "store.jsonl"
    write_jsonl(store, [_stored_instance()])

    instance, verdict = try_label(LABEL, "bacnet", store_path=str(store))
    assert verdict["method"] == "retrieval"
    assert verdict["needs_llm"] is False
    assert verdict["schema_errors"] == []
    assert instance["measurement_type"] == "temperatur"

    text = render(instance, verdict)
    assert "NOT need the LLM layer" in text
    assert '"raw_label"' in text


def test_try_label_junk_goes_to_llm(tmp_path):
    store = tmp_path / "store.jsonl"
    write_jsonl(store, [_stored_instance()])

    instance, verdict = try_label("lorem ipsum dolor sit amet", "other",
                                  store_path=str(store))
    assert verdict["needs_llm"] is True
    assert instance["raw_label"] == "lorem ipsum dolor sit amet"
    assert "residue.jsonl" in render(instance, verdict)
