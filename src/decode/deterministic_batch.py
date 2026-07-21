"""Layer 2 driver: decode a batch deterministically, cheapest first.

Per label: validated-store exact hit -> rules engine -> sibling inheritance
(rules-resolved fields win; siblings fill nulls). Labels that stay below the
usefulness bar go to residue.jsonl for the LLM layer -- this driver NEVER
calls an LLM and never spends tokens.

    python -m src.decode.deterministic_batch \
        --input data/eval/batches/<id>/input.jsonl --out-dir runs/<id>_det

Outputs: outputs.jsonl (decoded rows, schema-validated), residue.jsonl (input
rows for the LLM layer, original shape), coverage.md (the numbers), run_meta.json.
"""
import argparse
from collections import Counter
from pathlib import Path

from src.common.io_utils import configure_stdout_utf8, read_jsonl, write_json, write_jsonl
from src.decode.context_pack import build_context_pack
from src.decode.kb_lookup import decoder_state_version
from src.decode.retrieval import inherit_fields, retrieve, signature
from src.decode.rules_engine import FULL, NONE, PARTIAL, decode_rules
from src.validate.schema_validator import build_validator, validate_instance

# Below this bar a decode is too empty to be useful -> LLM residue.
MIN_CONFIDENCE = 0.4


def _tier_of(instance):
    key_fields = (instance.get("primary_system"), instance.get("component"),
                  instance.get("function"), instance.get("measurement_type"))
    resolved = sum(1 for f in key_fields if f is not None)
    return FULL if resolved >= 3 else (PARTIAL if resolved >= 1 else NONE)


def decode_deterministic(raw_label, source_type, store_path=None):
    """One label through store -> rules -> sibling. Returns (instance, tier, method)."""
    hit = retrieve(raw_label, store_path)
    if hit is not None and hit[0] == "exact":
        instance = dict(hit[1])
        instance["decode_method"] = "retrieval"
        return instance, _tier_of(instance), "retrieval"

    instance, tier = decode_rules(raw_label, source_type)
    method = "rules"
    if hit is not None:  # ('sibling', row)
        template = hit[1]
        donations = inherit_fields(template, raw_label)
        added = []
        for field, (value, note) in donations.items():
            if instance.get(field) is None:
                instance[field] = value
                added.append(f"{field} {note}")
        if added:
            method = "rules+retrieval"
            instance["decode_method"] = method
            instance["confidence"] = round(
                min(0.9, max(instance["confidence"],
                             (template.get("confidence") or 0.5) - 0.1)), 2)
            instance["reasoning"] = instance["reasoning"] + "; " + "; ".join(added)
            tier = _tier_of(instance)
    return instance, tier, method


def run(input_path, out_dir, schema_path=None, store_path=None):
    """Decode one batch; write outputs/residue/coverage/run_meta; return the meta dict.

    `store_path` overrides the validated-decodes store (used by tests to stay
    hermetic); None means the repo store.
    """
    rows = read_jsonl(input_path)
    _, kb_version = build_context_pack()
    validator = build_validator(schema_path)

    outputs, residue = [], []
    method_counts, tier_counts = Counter(), Counter()
    families = {}
    n_invalid = 0

    for row in rows:
        raw_label, source_type = row["raw_label"], row["source_type"]
        instance, tier, method = decode_deterministic(raw_label, source_type, store_path)
        instance["decoded_kb_version"] = kb_version

        fam = families.setdefault(signature(raw_label), Counter())
        fam[tier] += 1

        if tier == NONE or (instance.get("confidence") or 0) < MIN_CONFIDENCE:
            residue.append(row)
            tier_counts["residue"] += 1
            continue

        errors = validate_instance(instance, validator)
        if errors:
            n_invalid += 1
            residue.append(row)   # a broken deterministic decode goes to the LLM too
            tier_counts["residue"] += 1
            continue
        outputs.append(instance)
        method_counts[method] += 1
        tier_counts[tier] += 1

    out_dir = Path(out_dir)
    write_jsonl(out_dir / "outputs.jsonl", outputs)
    write_jsonl(out_dir / "residue.jsonl", residue)
    meta = {
        "decoder": "deterministic (rules + retrieval)",
        "kb_version": kb_version,
        "rules_version": decoder_state_version(),
        "input": str(input_path),
        "n": len(rows),
        "decoded": len(outputs),
        "residue": len(residue),
        "schema_invalid_deterministic": n_invalid,
        "methods": dict(method_counts),
        "tiers": dict(tier_counts),
    }
    if store_path:
        meta["store"] = str(store_path)
    write_json(out_dir / "run_meta.json", meta)

    # --- coverage report ------------------------------------------------------
    n = len(rows)
    L = ["# Deterministic decode coverage", ""]
    L.append(f"Input: `{input_path}` -- {n} labels · KB `{kb_version}` · zero LLM tokens")
    L.append("")
    L.append("## At a glance")
    L.append("")
    decoded_pct = 100 * len(outputs) / n if n else 0
    L.append(f"- Decoded deterministically: **{len(outputs)}/{n} ({decoded_pct:.1f}%)**")
    for method, count in sorted(method_counts.items()):
        L.append(f"  - {method}: {count}")
    L.append(f"- Tiers: FULL {tier_counts[FULL]} · PARTIAL {tier_counts[PARTIAL]}")
    L.append(f"- **Residue for the LLM layer: {len(residue)}**"
             + (f" (incl. {n_invalid} schema-invalid deterministic decodes)" if n_invalid else ""))
    L.append("")
    L.append("## Structural families")
    L.append("")
    L.append("| family signature | labels | tiers |")
    L.append("|---|---|---|")
    for sig, counts in sorted(families.items(), key=lambda kv: -sum(kv[1].values())):
        tiers = ", ".join(f"{t}:{c}" for t, c in sorted(counts.items()))
        short = sig if len(sig) <= 70 else "…" + sig[-69:]
        L.append(f"| `{short}` | {sum(counts.values())} | {tiers} |")
    L.append("")
    if residue:
        L.append("## Residue (needs the LLM layer)")
        L.append("")
        for row in residue:
            L.append(f"- `{row['raw_label']}`")
        L.append("")
    (out_dir / "coverage.md").write_text("\n".join(L), encoding="utf-8")
    return meta


def main() -> int:
    configure_stdout_utf8()
    ap = argparse.ArgumentParser(
        description="Deterministic batch decode (rules + retrieval, zero LLM tokens)."
    )
    ap.add_argument("--input", required=True, help="batch input.jsonl")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--schema", help="schema path (defaults to schema/decoded_label.schema.json)")
    args = ap.parse_args()

    meta = run(args.input, args.out_dir, args.schema)
    print(f"decoded {meta['decoded']}/{meta['n']} deterministically "
          f"({meta['methods']}), residue {meta['residue']} -> {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
