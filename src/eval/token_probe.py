"""Tokenizer robustness probe: find what the parser fails on, NOT fix it.

Runs the rules layer alone (no validated store, so KB recall cannot mask
parser gaps) over batch inputs and reports failure MODES, frequency-ranked:

- unrecognized path segments (clustered by digit-collapsed signature)
- labels whose component stayed null despite a code-like token in the label
- a mutation probe: structural variations (separator swaps, lowercase codes,
  displaced tokens) applied to labels that currently decode, showing which
  variations the parser survives -- brittleness a NEW vendor would expose.

    python -m src.eval.token_probe data/eval/batches/*/input.jsonl \
        -o runs/token_probe/report.md

The report is documentation of weaknesses, not a patch queue: fix categories
(generalize a pattern, document a grammar variant), never single labels.
"""
import argparse
import re
from collections import Counter, defaultdict
from pathlib import Path

from src.common.io_utils import configure_stdout_utf8, read_jsonl
from src.common.label_tokens import (
    BYGG_ETG,
    EMBEDDED_POINT_TAIL,
    EQUIPMENT_TOKEN,
    IO_POINT,
    MODBUS_TOKEN,
    PATH_OBJECT_TOKENS,
    POINT_CODE,
    ROOM,
    SETPOINT_SUFFIX,
    SUBSYS_COMPONENT,
    SYSTEM_TOKEN,
    path_segments,
)
from src.decode.kb_lookup import deterministic_rules
from src.decode.rules_engine import decode_rules

_DIGITS = re.compile(r"\d+")
# Anything that LOOKS like a component code, case-insensitive -- superset of
# what the tokenizer accepts, to catch codes the strict patterns miss.
CODE_LIKE = re.compile(r"(?<![A-Za-z])([A-Za-z]{2}\d{2,3})(?!\d)")

FIELDS = ("primary_system", "subsystem", "component", "function",
          "measurement_type", "object_type", "location", "carrier")


def _segment_recognized(segment, keywords):
    """True if any structural pattern or curated keyword claims this segment."""
    core = SETPOINT_SUFFIX.sub("", segment)
    if (SYSTEM_TOKEN.match(segment) or EQUIPMENT_TOKEN.match(segment)
            or POINT_CODE.match(core) or IO_POINT.match(core.lstrip("-"))
            or MODBUS_TOKEN.match(segment) or SUBSYS_COMPONENT.match(segment)
            or EMBEDDED_POINT_TAIL.search(core) or BYGG_ETG.search(segment)
            or ROOM.search(segment)):
        return True
    if segment.casefold() in PATH_OBJECT_TOKENS:
        return True
    hay = segment.casefold()
    return any(k in hay for k in keywords)


# Structural mutations a new vendor/site could plausibly introduce. Each takes
# a raw label and returns a mutated label or None when not applicable.
def _swap_seps(label):
    if "-" in label.split("/", 1)[-1] or "_" in label:
        return label.split("/", 1)[0] + "/" + (
            label.split("/", 1)[-1].translate(str.maketrans("-_", "_-")))
    return None


def _lowercase_codes(label):
    out = CODE_LIKE.sub(lambda m: m.group(1).lower(), label)
    return out if out != label else None


def _space_separators(label):
    head, _, path = label.partition("/")
    if "-" not in path and "_" not in path:
        return None
    return head + "/" + path.replace("-", " ").replace("_", " ")


def _displace_code(label):
    """Move a trailing code off the segment end: `..-SB602.#85` -> `..-SB602_X.#85`."""
    head, sep, tag = label.rpartition(".#")
    if not sep:
        return None
    return head + "_X." + "#" + tag


MUTATIONS = {
    "swap - and _": _swap_seps,
    "lowercase codes": _lowercase_codes,
    "spaces for separators": _space_separators,
    "code not at segment end": _displace_code,
}


def probe(input_paths):
    keywords = sorted(deterministic_rules()["point_name_keywords"])
    rows = []
    for p in input_paths:
        rows.extend(read_jsonl(p))

    null_counts, tier_counts = Counter(), Counter()
    unrecognized = defaultdict(list)          # signature -> [segment examples]
    missed_codes = []                          # (label, code-like tokens)
    decoded = []                               # (row, instance) that resolved something

    for row in rows:
        instance, tier = decode_rules(row["raw_label"], row["source_type"])
        tier_counts[tier] += 1
        for f in FIELDS:
            if instance.get(f) is None:
                null_counts[f] += 1
        for seg in path_segments(row["raw_label"]):
            if not _segment_recognized(seg, keywords):
                unrecognized[_DIGITS.sub("#", seg).casefold()].append(seg)
        if instance.get("component") is None:
            codes = CODE_LIKE.findall(row["raw_label"].split(":", 1)[-1])
            if codes:
                missed_codes.append((row["raw_label"], sorted(set(codes))))
        if instance.get("component") or instance.get("object_type"):
            decoded.append(row)

    # Mutation probe over every decodable label: which structural variations
    # does the parser survive?  survived = field-for-field no loss vs original.
    mutation_stats = {name: Counter() for name in MUTATIONS}
    for row in decoded:
        base, _ = decode_rules(row["raw_label"], row["source_type"])
        for name, fn in MUTATIONS.items():
            mutated = fn(row["raw_label"])
            if mutated is None:
                continue
            got, _ = decode_rules(mutated, row["source_type"])
            lost = [f for f in FIELDS if base.get(f) is not None and got.get(f) is None]
            mutation_stats[name]["tried"] += 1
            if lost:
                mutation_stats[name]["broke"] += 1
                for f in lost:
                    mutation_stats[name][f"lost:{f}"] += 1

    return {
        "n": len(rows), "tiers": dict(tier_counts), "nulls": dict(null_counts),
        "unrecognized": unrecognized, "missed_codes": missed_codes,
        "mutations": mutation_stats,
    }


def render(result):
    n = result["n"]
    L = ["# Tokenizer robustness probe", ""]
    L.append(f"{n} labels, rules layer only (no validated store). "
             "This reports failure MODES to understand, not labels to patch.")
    L.append("")
    L.append(f"## Tiers: {result['tiers']}")
    L.append("")
    L.append("## Field null rates (rules only)")
    L.append("")
    for f, c in sorted(result["nulls"].items(), key=lambda kv: -kv[1]):
        L.append(f"- {f}: {c}/{n} null ({100 * c / n:.0f}%)")
    L.append("")
    L.append("## Unrecognized segment families (frequency-ranked)")
    L.append("")
    L.append("Path segments no structural pattern or curated keyword claims.")
    L.append("")
    L.append("| family (digits -> #) | count | example |")
    L.append("|---|---|---|")
    fams = sorted(result["unrecognized"].items(), key=lambda kv: -len(kv[1]))
    for sig, examples in fams[:30]:
        L.append(f"| `{sig[:60]}` | {len(examples)} | `{examples[0][:60]}` |")
    if len(fams) > 30:
        L.append("")
        L.append(f"... and {len(fams) - 30} more families (see probe output).")
    L.append("")
    L.append("## Component null despite code-like tokens")
    L.append("")
    L.append(f"{len(result['missed_codes'])} labels have no component but "
             "contain code-like tokens the strict patterns rejected:")
    L.append("")
    seen = Counter()
    for label, codes in result["missed_codes"]:
        key = ",".join(codes)
        seen[key] += 1
        if seen[key] == 1:
            L.append(f"- `{label[-70:]}` -> candidates {codes}")
    L.append("")
    L.append("## Mutation probe (structural variations a new site could use)")
    L.append("")
    L.append("| mutation | tried | broke | loss rate | top losses |")
    L.append("|---|---|---|---|---|")
    for name, st in result["mutations"].items():
        tried, broke = st.get("tried", 0), st.get("broke", 0)
        losses = ", ".join(f"{k[5:]}:{v}" for k, v in st.most_common()
                           if k.startswith("lost:"))[:60]
        rate = f"{100 * broke / tried:.0f}%" if tried else "n/a"
        L.append(f"| {name} | {tried} | {broke} | {rate} | {losses} |")
    L.append("")
    return "\n".join(L)


def main() -> int:
    configure_stdout_utf8()
    ap = argparse.ArgumentParser(description="Probe tokenizer robustness over batch inputs.")
    ap.add_argument("inputs", nargs="+", help="batch input.jsonl paths")
    ap.add_argument("-o", "--out", required=True, help="markdown report path")
    args = ap.parse_args()

    result = probe(args.inputs)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(result), encoding="utf-8")
    print(f"probed {result['n']} labels -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
