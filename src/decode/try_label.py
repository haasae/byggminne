"""Manual single-label test: put in one label, see the structured output.

Runs the deterministic layer only (validated store -> rules -> sibling
inheritance; zero LLM tokens) and prints everything a human needs to judge the
result: the decoded JSON, how it was decoded, the confidence, whether it
validates against the schema, and whether the batch pipeline would hand this
label on to the LLM layer.

    python -m src.decode.try_label "PS4001:472-OU001/-RT401.#1" --source-type bacnet

For batch testing with metrics, use `python -m src.eval.run_eval` instead
(see docs/EVALUATION.md).
"""
import argparse
import json

from src.common.io_utils import configure_stdout_utf8
from src.decode.deterministic_batch import MIN_CONFIDENCE, decode_deterministic
from src.decode.rules_engine import NONE
from src.validate.schema_validator import build_validator, validate_instance


def try_label(raw_label, source_type="other", store_path=None, schema_path=None):
    """Decode one label deterministically; return (instance, verdict).

    verdict: {"tier", "method", "schema_errors", "needs_llm"} -- `needs_llm`
    mirrors the residue bar in deterministic_batch (tier NONE, confidence below
    MIN_CONFIDENCE, or a schema-invalid instance).
    """
    instance, tier, method = decode_deterministic(raw_label, source_type, store_path)
    errors = validate_instance(instance, build_validator(schema_path))
    needs_llm = (
        tier == NONE
        or (instance.get("confidence") or 0) < MIN_CONFIDENCE
        or bool(errors)
    )
    verdict = {
        "tier": tier,
        "method": method,
        "schema_errors": errors,
        "needs_llm": needs_llm,
    }
    return instance, verdict


_METHOD_TEXT = {
    "retrieval": "exact hit in the validated store -- this replays a decode a "
                 "human already validated",
    "rules": "rules engine (curated keywords / component codes / side digits)",
    "rules+retrieval": "rules engine, with missing fields inherited from a "
                       "structural sibling in the validated store",
}


def render(instance, verdict):
    """Human-readable report for one tried label."""
    L = [f"Label: {instance['raw_label']}", ""]
    L.append(f"- Decoded by: {verdict['method']} "
             f"({_METHOD_TEXT.get(verdict['method'], 'unknown method')})")
    L.append(f"- Completeness tier: {verdict['tier']} · "
             f"confidence {instance.get('confidence')}")
    if verdict["schema_errors"]:
        L.append(f"- Schema: INVALID -- {len(verdict['schema_errors'])} error(s):")
        for path, msg in verdict["schema_errors"]:
            L.append(f"    - {path}: {msg}")
    else:
        L.append("- Schema: valid")
    if verdict["needs_llm"]:
        L.append("- Verdict: the deterministic layer can NOT decode this well "
                 "enough on its own. In the batch pipeline this label goes to "
                 "residue.jsonl for the LLM layer (see docs/EVALUATION.md).")
    else:
        L.append("- Verdict: good enough deterministically -- this label would "
                 "NOT need the LLM layer.")
    L.append("")
    L.append("Structured output:")
    L.append(json.dumps(instance, ensure_ascii=False, indent=2))
    return "\n".join(L)


def main() -> int:
    configure_stdout_utf8()
    ap = argparse.ArgumentParser(
        description="Decode ONE label deterministically and show the structured "
                    "output plus a plain-language verdict. Zero LLM tokens."
    )
    ap.add_argument("label", help="the raw label to decode (quote it)")
    ap.add_argument("--source-type", default="other",
                    choices=["kiona", "bacnet", "other"],
                    help="where the label comes from (default: other; it is "
                         "carried into the output, not used to branch)")
    ap.add_argument("--store", help="validated-decodes store override (mainly for tests)")
    ap.add_argument("--schema", help="schema path (defaults to schema/decoded_label.schema.json)")
    args = ap.parse_args()

    instance, verdict = try_label(args.label, args.source_type,
                                  store_path=args.store, schema_path=args.schema)
    print(render(instance, verdict))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
