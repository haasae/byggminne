"""Merge LLM enrichment decodes into deterministic outputs.

Policy (auditable, deterministic-first):
1. The deterministic row is the base; its non-null fields ALWAYS win -- every
   deterministic field carries a KB citation in `reasoning` by construction.
2. An LLM value is adopted only into a still-null field; each adoption is noted
   in `reasoning`.
3. A conflict (both non-null, unequal) never overwrites silently: the
   deterministic value stays and the conflict goes to merge_conflicts.jsonl
   for human review.
4. Confidence after >=1 adoption: round(min(0.90, max(det, llm - 0.1)), 2) --
   the same shape as sibling inheritance in deterministic_batch.
5. `validated` stays false; every merged row is schema-validated.

    python -m src.decode.merge_outputs --deterministic runs/<id>/outputs.jsonl \
        --llm runs/<id>_enrich/outputs_llm.jsonl \
        --out runs/<id>_enrich/outputs_enriched.jsonl
"""
import argparse
from pathlib import Path

from src.common.io_utils import configure_stdout_utf8, read_jsonl, write_jsonl
from src.validate.schema_validator import build_validator, validate_instance

# Semantic fields an LLM enrichment may fill. Never merged: identity/provenance
# fields (raw_label, source_type, confidence, reasoning, validated,
# decode_method, decoded_kb_version, data_checks, relationships).
MERGE_FIELDS = (
    "carrier", "function", "measurement_type", "unit", "object_type",
    "primary_system", "subsystem", "component", "is_derived",
)
CONFIDENCE_CAP = 0.90


def merge_row(det, llm):
    """Merge one LLM row into one deterministic row.

    Returns (merged, adopted_fields, conflicts) -- conflicts are
    {"field", "deterministic", "llm"} dicts; `merged` is a new dict.
    """
    merged = dict(det)
    adopted, conflicts = [], []
    kb = llm.get("decoded_kb_version") or "?"

    for field in MERGE_FIELDS:
        det_val, llm_val = det.get(field), llm.get(field)
        if llm_val is None:
            continue
        if det_val is None:
            merged[field] = llm_val
            adopted.append(field)
        elif det_val != llm_val:
            conflicts.append({"field": field,
                              "deterministic": det_val, "llm": llm_val})

    # location merges member-wise: adopt the whole object into null, else
    # fill null members; member conflicts are logged like any other.
    det_loc, llm_loc = det.get("location"), llm.get("location")
    if llm_loc is not None:
        if det_loc is None:
            merged["location"] = dict(llm_loc)
            adopted.append("location")
        else:
            new_loc = dict(det_loc)
            for member in ("building", "zone"):
                det_m, llm_m = det_loc.get(member), llm_loc.get(member)
                if llm_m is None:
                    continue
                if det_m is None:
                    new_loc[member] = llm_m
                    adopted.append(f"location.{member}")
                elif det_m != llm_m:
                    conflicts.append({"field": f"location.{member}",
                                      "deterministic": det_m, "llm": llm_m})
            merged["location"] = new_loc

    if adopted:
        det_conf = det.get("confidence") or 0
        llm_conf = llm.get("confidence") or 0
        merged["confidence"] = round(
            min(CONFIDENCE_CAP, max(det_conf, llm_conf - 0.1)), 2)
        merged["decode_method"] = f"{det.get('decode_method') or 'rules'}+llm"
        note = f"{', '.join(adopted)} from llm enrichment (kb {kb})"
        merged["reasoning"] = (f"{det['reasoning']}; {note}"
                               if det.get("reasoning") else note)
    return merged, adopted, conflicts


def merge(det_rows, llm_rows, schema_path=None):
    """Merge all rows. Returns (merged_rows, conflicts, stats)."""
    validator = build_validator(schema_path)
    det_by_label = {r["raw_label"]: r for r in det_rows}
    llm_by_label = {}
    stats = {"llm_rows": len(llm_rows), "llm_schema_invalid": 0,
             "llm_unknown_label": 0, "rows_enriched": 0, "conflict_rows": 0}

    for row in llm_rows:
        if row.get("schema_invalid"):
            stats["llm_schema_invalid"] += 1
            continue
        if row["raw_label"] not in det_by_label:
            stats["llm_unknown_label"] += 1
            continue
        llm_by_label[row["raw_label"]] = row

    merged_rows, conflict_log = [], []
    for det in det_rows:
        llm = llm_by_label.get(det["raw_label"])
        if llm is None:
            merged_rows.append(det)
            continue
        merged, adopted, conflicts = merge_row(det, llm)
        if conflicts:
            stats["conflict_rows"] += 1
            for c in conflicts:
                conflict_log.append({"raw_label": det["raw_label"], **c})
        errors = validate_instance(merged, validator)
        if errors:
            # A merge must never break the contract: keep the deterministic
            # row and surface the problem instead of writing a broken row.
            conflict_log.append({"raw_label": det["raw_label"],
                                 "field": "_schema",
                                 "deterministic": "kept",
                                 "llm": f"merge invalid: {errors}"})
            merged_rows.append(det)
            continue
        if adopted:
            stats["rows_enriched"] += 1
        merged_rows.append(merged)
    return merged_rows, conflict_log, stats


def main() -> int:
    configure_stdout_utf8()
    ap = argparse.ArgumentParser(
        description="Merge LLM enrichment rows into deterministic outputs "
                    "(deterministic non-null fields always win)."
    )
    ap.add_argument("--deterministic", required=True)
    ap.add_argument("--llm", required=True)
    ap.add_argument("--out", required=True, help="merged outputs.jsonl path")
    ap.add_argument("--schema", help="schema path (defaults to schema/decoded_label.schema.json)")
    args = ap.parse_args()

    det_rows = read_jsonl(args.deterministic)
    llm_rows = read_jsonl(args.llm)
    merged_rows, conflicts, stats = merge(det_rows, llm_rows, args.schema)

    out = Path(args.out)
    write_jsonl(out, merged_rows)
    conflicts_path = out.parent / "merge_conflicts.jsonl"
    write_jsonl(conflicts_path, conflicts)
    print(f"enriched {stats['rows_enriched']}/{len(det_rows)} rows "
          f"({stats['llm_rows']} llm rows: {stats['llm_schema_invalid']} invalid, "
          f"{stats['llm_unknown_label']} unknown labels) -> {out}")
    print(f"{len(conflicts)} conflicts -> {conflicts_path}"
          if conflicts else "no conflicts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
