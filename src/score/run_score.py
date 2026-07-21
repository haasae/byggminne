"""Score decoder outputs against gold and write report.md / report.json / errors.jsonl.

The scoring harness makes ZERO model calls: it consumes an outputs.jsonl and a
gold.jsonl and is fully deterministic. It can score any outputs file from any
decoder, model, or run.

    python -m src.score.run_score --outputs runs/<id>/outputs.jsonl \
        --gold tests/gold/<batch>/gold.jsonl --out-dir runs/<id>
"""
import argparse
from pathlib import Path

from src.common.io_utils import (
    configure_stdout_utf8,
    read_jsonl,
    write_json,
    write_jsonl,
)
from src.score.align import align
from src.score.metrics import compute_metrics
from src.score.report import build_error_rows, metrics_to_json, render_markdown
from src.validate.schema_validator import build_validator, validate_instance


def score(outputs, gold, schema_path=None):
    """Run the full scoring pipeline; return (metrics, alignment, schema_invalid)."""
    validator = build_validator(schema_path)
    schema_valid_map, schema_invalid = {}, {}
    for row in outputs:
        key = row.get("raw_label")
        errs = validate_instance(row, validator)
        schema_valid_map[key] = not errs
        if errs:
            schema_invalid[key] = errs

    alignment = align(outputs, gold)
    metrics = compute_metrics(
        alignment.matched,
        schema_valid_map=schema_valid_map,
        n_outputs=len(outputs),
    )
    metrics["integrity"] = {
        "missing_in_outputs": alignment.missing_in_outputs,
        "extra_in_outputs": alignment.extra_in_outputs,
        "duplicate_output_keys": alignment.duplicate_output_keys,
        "duplicate_gold_keys": alignment.duplicate_gold_keys,
        "near_miss_keys": alignment.near_miss_keys,
    }
    return metrics, alignment, schema_invalid


def write_score_reports(out_dir, metrics, schema_invalid):
    """Write errors.jsonl / report.json / report.md; return the markdown."""
    out_dir = Path(out_dir)
    write_jsonl(out_dir / "errors.jsonl", build_error_rows(metrics, schema_invalid))
    write_json(out_dir / "report.json", metrics_to_json(metrics))
    report_md = render_markdown(metrics)
    (out_dir / "report.md").write_text(report_md, encoding="utf-8")
    return report_md


def main() -> int:
    configure_stdout_utf8()
    ap = argparse.ArgumentParser(description="Score outputs.jsonl against gold.jsonl.")
    ap.add_argument("--outputs", required=True)
    ap.add_argument("--gold", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--schema", help="schema path (defaults to schema/decoded_label.schema.json)")
    args = ap.parse_args()

    outputs = read_jsonl(args.outputs)
    gold = read_jsonl(args.gold)
    metrics, _, schema_invalid = score(outputs, gold, args.schema)
    report_md = write_score_reports(args.out_dir, metrics, schema_invalid)

    print(report_md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
