from pathlib import Path

from src.common.io_utils import read_jsonl
from src.score.metrics import compute_metrics
from src.score.report import build_error_rows
from src.score.run_score import score

FIXTURES = Path(__file__).parent / "fixtures"


def _load():
    outputs = read_jsonl(FIXTURES / "mini_outputs.jsonl")
    gold = read_jsonl(FIXTURES / "mini_gold.jsonl")
    return outputs, gold


def test_headline_rates():
    metrics, _, schema_invalid = score(*_load())
    assert metrics["n_matched"] == 2
    assert metrics["exact_match_rate"] == 0.5   # L1 fully correct, L2 not
    assert metrics["core_exact_rate"] == 0.5
    assert metrics["schema_validity_rate"] == 1.0
    assert schema_invalid == {}


def test_per_field_verdict_counts():
    metrics, _, _ = score(*_load())
    stats = metrics["field_stats"]
    assert stats["measurement_type"].wrong_value == 1
    assert stats["function"].under_fill == 1        # L2: gold status, pred null
    assert stats["component"].over_fill == 1         # L2: pred RT, gold null
    assert stats["subsystem"].wrong_value == 1       # L2: retur vs tur
    # code: prefix headline correct once (L1), exact never (3600!=360, 370!=320)
    assert stats["primary_system.code"].overall_correct == 1
    assert stats["primary_system.code"].exact_total == 2
    assert stats["primary_system.code"].exact_correct == 0


def test_nontrivial_excludes_null_gold():
    metrics, _, _ = score(*_load())
    stats = metrics["field_stats"]
    # carrier is null in both gold rows -> nothing non-trivial to score.
    assert stats["carrier"].nontrivial_total == 0
    # object_type is non-null on both bacnet rows and both correct.
    assert stats["object_type"].nontrivial_total == 2
    assert stats["object_type"].nontrivial_correct == 2


def test_brier_score():
    metrics, _, _ = score(*_load())
    cal = metrics["calibration"]
    # L1 conf 0.9 correct(1): 0.01 ; L2 conf 0.4 correct(0): 0.16 ; mean 0.085
    assert abs(cal["brier"] - 0.085) < 1e-9
    assert cal["n"] == 2


def test_error_rows_include_kinds_and_schema_invalid():
    metrics, _, _ = score(*_load())
    rows = build_error_rows(metrics, schema_invalid={"Lx": [("carrier", "bad enum")]})
    kinds = {r["kind"] for r in rows}
    assert {"UNDER_FILL", "OVER_FILL", "WRONG_VALUE", "SCHEMA_INVALID"} <= kinds
    # every non-schema error row carries the label + field it concerns
    for r in rows:
        assert "raw_label" in r and "field" in r


def test_compute_metrics_handles_empty():
    metrics = compute_metrics([], schema_valid_map={}, n_outputs=0)
    assert metrics["n_matched"] == 0
    assert metrics["exact_match_rate"] is None
