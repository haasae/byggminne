"""Graph-readiness report: how much of a decoded batch the Brick graph can use.

The four headline percentages ARE the working definition of "decoded well
enough for the knowledge graph":
- typed:     point maps to a Brick class more specific than brick:Point
- equipment: point belongs to a structural equipment group (anchoring)
- building:  point resolves to a building (else it floats at site level)
- system:    primary_system decoded (system node membership possible)

Runs on ANY outputs file (before or after enrichment), so run it first for a
baseline and again after each loop iteration.

    python -m src.brick.readiness_report --outputs runs/<id>/outputs.jsonl \
        --out-dir runs/<id>
"""
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from src.brick.emit_graph import equipment_keys
from src.brick.mapping import point_class, unit_iri
from src.common.io_utils import configure_stdout_utf8, read_jsonl
from src.common.readiness import readiness_gaps
from src.decode.retrieval import signature


def assess(rows):
    """Per-batch readiness metrics + a per-family gap table."""
    n = len(rows)
    typed = equipment = building = system = unit = 0
    class_counts = Counter()
    families = defaultdict(lambda: {"n": 0, "gaps": Counter(), "untyped": 0})

    for row in rows:
        cls, _ = point_class(row)
        class_counts[cls] += 1
        is_typed = cls != "Point"
        has_equipment = bool(equipment_keys(row["raw_label"]))
        has_building = bool((row.get("location") or {}).get("building"))
        has_system = row.get("primary_system") is not None
        has_unit = unit_iri(row.get("unit"))[0] is not None

        typed += is_typed
        equipment += has_equipment
        building += has_building
        system += has_system
        unit += has_unit

        fam = families[signature(row["raw_label"])]
        fam["n"] += 1
        fam["untyped"] += not is_typed
        for gap in readiness_gaps(row):
            fam["gaps"][gap] += 1

    def pct(x):
        return round(100 * x / n, 1) if n else None

    return {
        "n_rows": n,
        "pct_typed_beyond_point": pct(typed),
        "pct_equipment_anchored": pct(equipment),
        "pct_with_building": pct(building),
        "pct_with_system": pct(system),
        "pct_with_mapped_unit": pct(unit),
        "brick_class_counts": dict(class_counts.most_common()),
        "families": {
            sig: {"n": f["n"], "untyped": f["untyped"], "gaps": dict(f["gaps"])}
            for sig, f in sorted(families.items(),
                                 key=lambda kv: -(kv[1]["untyped"] + sum(kv[1]["gaps"].values())))
        },
    }


def render_markdown(metrics, outputs_path):
    L = ["# Graph-readiness report", ""]
    L.append(f"Outputs: `{outputs_path}` -- {metrics['n_rows']} decoded labels")
    L.append("")
    L.append("## Headline (the definition of 'decoded well enough')")
    L.append("")
    L.append(f"- Points typed beyond `brick:Point`: **{metrics['pct_typed_beyond_point']}%**")
    L.append(f"- Points anchored to an equipment group: **{metrics['pct_equipment_anchored']}%**")
    L.append(f"- Points with a building: **{metrics['pct_with_building']}%**")
    L.append(f"- Points with a system (`primary_system`): **{metrics['pct_with_system']}%**")
    L.append(f"- Points with a QUDT-mapped unit: {metrics['pct_with_mapped_unit']}%")
    L.append("")
    L.append("## Brick point classes")
    L.append("")
    for cls, count in metrics["brick_class_counts"].items():
        L.append(f"- `brick:{cls}`: {count}")
    L.append("")
    L.append("## Fix-next queue (families, worst first)")
    L.append("")
    L.append("| family signature | labels | untyped | gaps |")
    L.append("|---|---|---|---|")
    for sig, f in metrics["families"].items():
        if not f["untyped"] and not f["gaps"]:
            continue
        gaps = ", ".join(f"{g}:{c}" for g, c in sorted(f["gaps"].items())) or "-"
        short = sig if len(sig) <= 60 else "…" + sig[-59:]
        L.append(f"| `{short}` | {f['n']} | {f['untyped']} | {gaps} |")
    L.append("")
    L.append("Close gaps via: KB/rule additions (cheapest), the /enrich skill + "
             "`src.profile.promote` (LLM + data validation), or accept the gap "
             "(e.g. site-head labels without building information).")
    L.append("")
    return "\n".join(L)


def main() -> int:
    configure_stdout_utf8()
    ap = argparse.ArgumentParser(
        description="Measure how graph-ready a decoded outputs file is."
    )
    ap.add_argument("--outputs", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    rows = read_jsonl(args.outputs)
    metrics = assess(rows)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "graph_readiness.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md = render_markdown(metrics, args.outputs)
    (out_dir / "graph_readiness.md").write_text(md, encoding="utf-8")

    print(f"typed {metrics['pct_typed_beyond_point']}% · "
          f"equipment {metrics['pct_equipment_anchored']}% · "
          f"building {metrics['pct_with_building']}% · "
          f"system {metrics['pct_with_system']}% "
          f"({metrics['n_rows']} labels) -> {out_dir / 'graph_readiness.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
