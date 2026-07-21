"""End-to-end harness test: batch -> deterministic decode -> score -> summary.

Hermetic: its own tmp validated store, batch, and gold. The repo KB store is
never read, so results do not drift as knowledge_base/ grows.
"""
import pytest

from src.common.io_utils import read_json, read_jsonl, write_jsonl
from src.eval.run_eval import run_eval

LABEL_A = "TEST-BYGG-01:111-OU001/-RT401.#1"
LABEL_B = "TEST-BYGG-02:222-OU001/-LR401.#1"
LABEL_JUNK = "lorem ipsum dolor sit amet"


def _instance(raw_label, **over):
    inst = {
        "raw_label": raw_label,
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
    inst.update(over)
    return inst


@pytest.fixture()
def batch(tmp_path):
    """A 3-label batch: two exact store hits + one undecodable junk label."""
    store = tmp_path / "store.jsonl"
    write_jsonl(store, [
        _instance(LABEL_A),
        _instance(LABEL_B, component="LR401"),
    ])
    input_path = tmp_path / "input.jsonl"
    write_jsonl(input_path, [
        {"raw_label": LABEL_A, "source_type": "bacnet"},
        {"raw_label": LABEL_B, "source_type": "bacnet"},
        {"raw_label": LABEL_JUNK, "source_type": "other"},
    ])
    gold = tmp_path / "gold.jsonl"
    write_jsonl(gold, [
        _instance(LABEL_A),
        # decoder will replay the store's "temperatur" -> one wrong field
        _instance(LABEL_B, component="LR401", measurement_type="trykk"),
        # never decoded deterministically -> integrity miss
        _instance(LABEL_JUNK, source_type="other"),
    ])
    return store, input_path, gold


def test_run_eval_scores_batch_against_gold(tmp_path, batch):
    store, input_path, gold = batch
    out_dir = tmp_path / "run"
    result = run_eval(input_path, out_dir=out_dir, gold_path=gold,
                      store_path=str(store), name="testbatch")

    # coverage: the two store labels decode, junk is residue for the LLM leg
    assert result["meta"]["decoded"] == 2
    assert result["meta"]["residue"] == 1
    assert [r["raw_label"] for r in read_jsonl(out_dir / "residue.jsonl")] == [LABEL_JUNK]

    # the overlap stat is honest about memorization
    assert result["overlap"] == {"exact": 2, "sibling": 0, "unseen": 1, "store_rows": 2}

    # accuracy: A exact, B has exactly one wrong field, junk is missing
    report = read_json(out_dir / "report.json")
    assert report["n_matched"] == 2
    assert report["exact_match_rate"] == 0.5
    assert report["integrity"]["missing_in_outputs"] == [LABEL_JUNK]
    errors = read_jsonl(out_dir / "errors.jsonl")
    assert any(e["raw_label"] == LABEL_B and e["field"] == "measurement_type"
               for e in errors)

    for artifact in ("summary.md", "coverage.md", "showcase.md", "report.md"):
        assert (out_dir / artifact).exists(), artifact
    assert "/decode" in result["summary_md"]   # residue points at the LLM leg


def test_run_eval_without_gold_skips_accuracy(tmp_path, batch):
    store, input_path, _gold = batch
    out_dir = tmp_path / "run_nogold"
    result = run_eval(input_path, out_dir=out_dir, store_path=str(store),
                      name="testbatch")
    assert result["metrics"] is None
    assert not (out_dir / "report.json").exists()
    assert "accuracy skipped" in result["summary_md"]
    assert (out_dir / "showcase.md").exists()


def test_run_eval_outputs_mode_scores_existing_file(tmp_path, batch):
    store, input_path, gold = batch
    det_dir = tmp_path / "det"
    run_eval(input_path, out_dir=det_dir, gold_path=gold,
             store_path=str(store), name="testbatch")

    # simulate the /decode skill: append an LLM row for the junk label
    outputs = read_jsonl(det_dir / "outputs.jsonl")
    outputs.append(_instance(LABEL_JUNK, source_type="other", decode_method="llm",
                             validated=False, confidence=0.5))
    merged = tmp_path / "merged" / "outputs.jsonl"
    write_jsonl(merged, outputs)

    out_dir = tmp_path / "rescore"
    result = run_eval(input_path, out_dir=out_dir, gold_path=gold,
                      outputs_path=merged, store_path=str(store), name="testbatch")
    report = read_json(out_dir / "report.json")
    assert report["n_matched"] == 3
    assert report["integrity"]["missing_in_outputs"] == []
    assert result["meta"]["residue"] == 0
