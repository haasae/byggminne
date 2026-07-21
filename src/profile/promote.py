"""Nominate data-confirmed LLM-enriched decodes for the validated store.

Closes the KB-accumulation loop: after /enrich + cross_check, this tool selects
rows whose LLM-contributed fields survived the data checks and writes a review
queue. It NEVER sets `validated: true` by itself -- the schema defines
`validated` as human-confirmed, so appending to the store requires the human
running --approve.

Candidate bar: decode_method contains "llm" AND no check verdict is CONFLICT
AND at least one check is PASS.

    # nominate
    python -m src.profile.promote --outputs runs/<id>/outputs_checked.jsonl \
        --checks runs/<id>/data_checks.jsonl --out-dir runs/<id>

    # human approval (appends to the validated store)
    python -m src.profile.promote --outputs ... --checks ... --out-dir ... \
        --approve "<raw_label>" ["<raw_label>" ...]
"""
import argparse
import json
from pathlib import Path

from src.common.io_utils import (
    configure_stdout_utf8,
    read_jsonl,
    repo_root,
    write_jsonl,
)
from src.decode.retrieval import STORE_FILE

PASS = "PASS"
CONFLICT = "CONFLICT"


def find_candidates(outputs, checks_rows):
    """(candidates, evidence_by_label): LLM-touched rows with clean data checks."""
    checks_by_label = {r["raw_label"]: r["checks"] for r in checks_rows}
    candidates, evidence = [], {}
    for row in outputs:
        method = row.get("decode_method") or ""
        if "llm" not in method:
            continue
        checks = checks_by_label.get(row["raw_label"])
        if not checks:
            continue                       # no data evidence -> not promotable
        verdicts = [c["verdict"] for c in checks]
        if CONFLICT in verdicts or PASS not in verdicts:
            continue
        candidates.append(row)
        evidence[row["raw_label"]] = [
            c for c in checks if c["verdict"] == PASS]
    return candidates, evidence


def approve(candidates, evidence, labels, store_path=None):
    """Append the approved candidates to the validated store (human action).

    Returns (appended_rows, skipped) -- skipped are labels not in the
    candidate set or already present in the store.
    """
    path = repo_root() / (store_path or STORE_FILE)
    existing = {r["raw_label"] for r in read_jsonl(path)} if path.exists() else set()
    by_label = {r["raw_label"]: r for r in candidates}

    appended, skipped = [], []
    for label in labels:
        row = by_label.get(label)
        if row is None or label in existing:
            skipped.append(label)
            continue
        promoted = dict(row)
        promoted["validated"] = True
        proof = "; ".join(f"{c['name']} {PASS} ({c['evidence']})"
                          for c in evidence.get(label, []))
        promoted["reasoning"] = (
            f"{row.get('reasoning') or ''}; human-approved after data "
            f"cross-check: {proof}").lstrip("; ")
        appended.append(promoted)

    if appended:
        with path.open("a", encoding="utf-8", newline="\n") as fh:
            for row in appended:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return appended, skipped


def _render_review(candidates, evidence, n_outputs):
    L = ["# Promotion review -- validated-store candidates", ""]
    L.append(f"{len(candidates)} of {n_outputs} rows qualify: LLM-touched, "
             "no data-check CONFLICT, at least one PASS.")
    L.append("")
    L.append("Approving a row appends it to `knowledge_base/validated_decodes.jsonl` "
             "with `validated: true`; sibling inheritance then spreads its "
             "STRUCTURAL fields across the family on the next deterministic run.")
    L.append("")
    for row in candidates:
        L.append(f"### `{row['raw_label']}`")
        L.append(f"- decode_method `{row.get('decode_method')}` · "
                 f"confidence {row.get('confidence')}")
        for field in ("primary_system", "measurement_type", "function",
                      "carrier", "component", "unit"):
            if row.get(field) is not None:
                L.append(f"- {field}: `{row[field]}`")
        for c in evidence.get(row["raw_label"], []):
            L.append(f"- data: **{c['name']} PASS** -- {c['evidence']}")
        L.append("")
    if not candidates:
        L.append("_No candidates -- run /enrich + cross_check first, or every "
                 "LLM row had a conflict._")
        L.append("")
    L.append("Approve with:")
    L.append("")
    L.append('    python -m src.profile.promote ... --approve "<raw_label>"')
    L.append("")
    return "\n".join(L)


def main() -> int:
    configure_stdout_utf8()
    ap = argparse.ArgumentParser(
        description="Nominate data-confirmed LLM decodes for the validated store."
    )
    ap.add_argument("--outputs", required=True,
                    help="outputs_checked.jsonl (from cross_check)")
    ap.add_argument("--checks", required=True,
                    help="data_checks.jsonl (from cross_check)")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--approve", nargs="+", metavar="RAW_LABEL",
                    help="append these candidate labels to the validated store")
    ap.add_argument("--store", help="validated-decodes store override (mainly for tests)")
    args = ap.parse_args()

    outputs = read_jsonl(args.outputs)
    checks_rows = read_jsonl(args.checks)
    candidates, evidence = find_candidates(outputs, checks_rows)

    out_dir = Path(args.out_dir)
    write_jsonl(out_dir / "promotion_candidates.jsonl", candidates)
    review = _render_review(candidates, evidence, len(outputs))
    (out_dir / "promotion_review.md").write_text(review, encoding="utf-8")
    print(f"{len(candidates)} promotion candidate(s) -> "
          f"{out_dir / 'promotion_review.md'}")

    if args.approve:
        appended, skipped = approve(candidates, evidence, args.approve, args.store)
        print(f"appended {len(appended)} row(s) to the validated store"
              + (f"; skipped {skipped}" if skipped else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
