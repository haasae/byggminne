"""Select thin-but-passing deterministic decodes for LLM enrichment.

The deterministic layer emits rows above its usefulness bar, but many are too
thin for the knowledge graph (no system, no point semantics, floor confidence).
This selector turns those rows into an enrichment residue the /enrich skill can
decode fresh -- WITHOUT changing the deterministic layer's own residue bar.

Building gaps are deliberately NOT selectable: when a label carries no building
information (e.g. the NIE site-head labels), an LLM cannot conjure one. That
gap stays visible in the graph-readiness report instead.

By default one representative per structural family (retrieval.signature) is
selected: a validated decode spreads across its family via the store's sibling
inheritance, which is the KB-accumulation way -- not one LLM call per sibling.

    python -m src.decode.enrichment --outputs runs/<id>/outputs.jsonl \
        --out-dir runs/<id>_enrich [--full]

Outputs: enrichment_residue.jsonl (input-shaped rows for the /enrich skill),
enrichment_manifest.jsonl (selection audit), enrichment_report.md.
"""
import argparse
from collections import Counter
from pathlib import Path

from src.common.io_utils import configure_stdout_utf8, read_jsonl, write_jsonl
from src.common.readiness import (
    GAP_BUILDING,
    GAP_LOW_CONFIDENCE,
    GAP_POINT_SEMANTICS,
    GAP_PRIMARY_SYSTEM,
    readiness_gaps,
)
from src.decode.retrieval import signature

# Gaps an LLM can plausibly close from the label + knowledge base.
SELECTABLE_GAPS = frozenset(
    {GAP_PRIMARY_SYSTEM, GAP_POINT_SEMANTICS, GAP_LOW_CONFIDENCE}
)


def select(rows, dedupe_families=True):
    """Pick enrichment candidates from decoded rows.

    Returns (residue_rows, manifest_rows). Residue rows are input-shaped
    ({raw_label, source_type}) so prompt_builder consumes them unchanged.
    
    """
    candidates = []
    for row in rows:
        gaps = readiness_gaps(row)
        selectable = tuple(g for g in gaps if g in SELECTABLE_GAPS)
        if selectable:
            candidates.append((row, gaps, selectable))

    family_sizes = Counter(signature(row["raw_label"]) for row, _, _ in candidates)
    if dedupe_families:
        # Deterministic representative: lexicographically first raw_label.
        best = {}
        for row, gaps, selectable in candidates:
            sig = signature(row["raw_label"])
            if sig not in best or row["raw_label"] < best[sig][0]["raw_label"]:
                best[sig] = (row, gaps, selectable)
        candidates = sorted(best.values(), key=lambda c: c[0]["raw_label"])

    residue, manifest = [], []
    for row, gaps, selectable in candidates:
        sig = signature(row["raw_label"])
        residue.append({"raw_label": row["raw_label"],
                        "source_type": row["source_type"]})
        manifest.append({
            "raw_label": row["raw_label"],
            "gaps": list(gaps),
            "selected_for": list(selectable),
            "family_signature": sig,
            "family_size": family_sizes[sig],
            "deterministic_confidence": row.get("confidence"),
            "deterministic_method": row.get("decode_method"),
        })
    return residue, manifest


def _render_report(rows, residue, manifest, dedupe_families):
    gap_counts = Counter(g for row in rows for g in readiness_gaps(row))
    L = ["# Enrichment selection", ""]
    L.append(f"Decoded rows in: {len(rows)} -- selected for LLM enrichment: "
             f"**{len(residue)}**"
             + (" (one representative per structural family)"
                if dedupe_families else " (--full: every gapped row)"))
    L.append("")
    L.append("## Readiness gaps across ALL rows")
    L.append("")
    for gap, count in gap_counts.most_common():
        note = " (not selectable -- not closable from the label)" \
            if gap == GAP_BUILDING else ""
        L.append(f"- {gap}: {count}{note}")
    L.append("")
    if manifest:
        L.append("## Selected representatives")
        L.append("")
        L.append("| raw_label | family size | selected for | det conf |")
        L.append("|---|---|---|---|")
        for m in manifest:
            label = m["raw_label"]
            short = label if len(label) <= 60 else "…" + label[-59:]
            L.append(f"| `{short}` | {m['family_size']} | "
                     f"{', '.join(m['selected_for'])} | "
                     f"{m['deterministic_confidence']} |")
        L.append("")
        L.append("Next: run the /enrich skill on `enrichment_residue.jsonl` "
                 "(fresh subagent per label), then merge with "
                 "`python -m src.decode.merge_outputs`.")
    else:
        L.append("Nothing to enrich -- every row clears the readiness bar.")
    L.append("")
    return "\n".join(L)


def run(outputs_path, out_dir, dedupe_families=True):
    """Select, write the three artifacts, return (residue, manifest)."""
    rows = read_jsonl(outputs_path)
    residue, manifest = select(rows, dedupe_families)
    out_dir = Path(out_dir)
    write_jsonl(out_dir / "enrichment_residue.jsonl", residue)
    write_jsonl(out_dir / "enrichment_manifest.jsonl", manifest)
    report = _render_report(rows, residue, manifest, dedupe_families)
    (out_dir / "enrichment_report.md").write_text(report, encoding="utf-8")
    return residue, manifest


def main() -> int:
    configure_stdout_utf8()
    ap = argparse.ArgumentParser(
        description="Select thin deterministic decodes for LLM enrichment."
    )
    ap.add_argument("--outputs", required=True,
                    help="deterministic outputs.jsonl to select from")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--full", action="store_true",
                    help="select every gapped row instead of one family representative")
    args = ap.parse_args()

    residue, _ = run(args.outputs, args.out_dir, dedupe_families=not args.full)
    print(f"{len(residue)} labels selected for enrichment -> "
          f"{args.out_dir}/enrichment_residue.jsonl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
