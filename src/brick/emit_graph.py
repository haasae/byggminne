"""Emit Brick Schema graphs (Turtle) from decoded outputs -- one per building.

Model, conservative by design:
- Site -> Building via brick:isPartOf; rows without a building go to the
  site-level file (<site>_site.ttl) -- honest "unplaced", never guessed.
- Equipment nodes come from the structural same_equipment group keys
  (src/common/label_tokens.group_keys), typed via brick_mapping.json;
  brick:hasLocation only when every member point agrees on the building.
- System nodes come from the label's own system token (structural evidence);
  a row whose primary_system rests only on a keyword hint gets its point
  class but NO system membership. System brick:hasPart equipment only when
  all of the equipment's members share the system token.
- Points: typed via brick_mapping.point_class; traceability = rdfs:label
  carrying the verbatim raw_label (UTF-8 preserved); brick:hasUnit when the
  unit maps to QUDT. brick:timeseries is deliberately unused (it references
  external timeseries DBs we do not have).
- NON-GOAL this round: brick:feeds. The tur/retur data checks order POINTS on
  a circuit, not equipment-to-equipment flow -- emitting feeds would be a
  guess.

    python -m src.brick.emit_graph --outputs runs/<id>/outputs_linked.jsonl \
        --site tasen --out-dir runs/<id>/graphs [--base-iri IRI]
"""
import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

from rdflib import Graph, Literal, Namespace, RDF, RDFS, URIRef

from src.brick.mapping import (
    BRICK,
    equipment_class,
    mapping_version,
    point_class,
    system_class,
    unit_iri,
)
from src.common.io_utils import configure_stdout_utf8, read_jsonl
from src.common.label_tokens import group_keys, point_token_of, system_token_of

BRICK_NS = Namespace(BRICK)
DEFAULT_BASE = "https://example.org/byggminne/"


def equipment_keys(raw_label):
    """same_equipment group keys, EXCLUDING the label's own point code: a bare
    component token like `RT401` names the point itself, not a device the
    point belongs to."""
    core, _ = point_token_of(raw_label)
    own = (core or "").lstrip("-")
    return [key for kind, key in group_keys(raw_label)
            if kind == "same_equipment" and key != own]


def sanitize(text):
    """ASCII-only IRI local name; hash-suffixed when lossy so names stay unique."""
    clean = re.sub(r"[^A-Za-z0-9_]+", "_", text or "").strip("_")
    if clean == text and clean:
        return clean
    suffix = hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:6]
    return f"{clean}_{suffix}" if clean else suffix


def _building_of(row):
    return ((row.get("location") or {}).get("building")) or None


def build_graphs(rows, site, base_iri=None):
    """Partition rows by building and emit rdflib Graphs.

    Returns (graphs, meta): graphs maps file-stem -> Graph; meta holds counts.
    """
    ex = Namespace(base_iri or f"{DEFAULT_BASE}{sanitize(site)}#")
    site_node = ex[f"site_{sanitize(site)}"]

    usable = [r for r in rows if not r.get("schema_invalid")]
    skipped = len(rows) - len(usable)

    # Cross-row evidence: which buildings / system tokens each equipment spans.
    equip_buildings, equip_systems = defaultdict(set), defaultdict(set)
    for row in usable:
        digits, _ = system_token_of(row["raw_label"])
        for key in equipment_keys(row["raw_label"]):
            equip_buildings[key].add(_building_of(row))
            equip_systems[key].add(digits)

    graphs, counts = {}, {}

    def graph_for(building):
        stem = f"{sanitize(site)}_{sanitize(building)}" if building \
            else f"{sanitize(site)}_site"
        if stem not in graphs:
            g = Graph()
            g.bind("brick", BRICK_NS)
            g.bind("rdfs", RDFS)
            g.add((site_node, RDF.type, BRICK_NS.Site))
            g.add((site_node, RDFS.label, Literal(site)))
            if building:
                b = ex[f"building_{sanitize(building)}"]
                g.add((b, RDF.type, BRICK_NS.Building))
                g.add((b, RDFS.label, Literal(building)))
                g.add((b, BRICK_NS.isPartOf, site_node))
            graphs[stem] = g
            counts[stem] = {"points": 0, "equipment": set(), "systems": set()}
        return stem, graphs[stem]

    def ensure_system(g, stem, digits, row):
        code4 = (row.get("primary_system") or {}).get("code") or f"{digits[:3]}0"
        cls, _ = system_class(code4)
        node = ex[f"system_{digits}"]
        g.add((node, RDF.type, BRICK_NS[cls]))
        desc = (row.get("primary_system") or {}).get("description") or ""
        g.add((node, RDFS.label, Literal(f"NS {code4} {desc} (token {digits})".strip())))
        counts[stem]["systems"].add(digits)
        return node

    def ensure_equipment(g, stem, key):
        cls, _ = equipment_class(key)
        node = ex[f"equipment_{sanitize(key)}"]
        g.add((node, RDF.type, BRICK_NS[cls]))
        g.add((node, RDFS.label, Literal(key)))
        buildings = equip_buildings[key]
        if len(buildings) == 1 and next(iter(buildings)):
            b = ex[f"building_{sanitize(next(iter(buildings)))}"]
            g.add((node, BRICK_NS.hasLocation, b))
        systems = {d for d in equip_systems[key] if d}
        if len(systems) == 1 and len(equip_systems[key]) == 1:
            g.add((ex[f"system_{next(iter(systems))}"], BRICK_NS.hasPart, node))
        counts[stem]["equipment"].add(key)
        return node

    for row in usable:
        building = _building_of(row)
        stem, g = graph_for(building)

        point = ex[f"point_{hashlib.sha1(row['raw_label'].encode('utf-8')).hexdigest()[:12]}"]
        cls, _ = point_class(row)
        g.add((point, RDF.type, BRICK_NS[cls]))
        g.add((point, RDFS.label, Literal(row["raw_label"])))
        iri, _ = unit_iri(row.get("unit"))
        if iri:
            g.add((point, BRICK_NS.hasUnit, URIRef(iri)))

        digits, _ = system_token_of(row["raw_label"])
        equipment = equipment_keys(row["raw_label"])
        if equipment:
            node = ensure_equipment(g, stem, equipment[0])
            g.add((point, BRICK_NS.isPointOf, node))
            if digits:
                ensure_system(g, stem, digits, row)
        elif digits:
            node = ensure_system(g, stem, digits, row)
            g.add((node, BRICK_NS.hasPoint, point))
        elif building:
            g.add((point, BRICK_NS.isPointOf, ex[f"building_{sanitize(building)}"]))
        else:
            g.add((point, BRICK_NS.isPointOf, site_node))
        counts[stem]["points"] += 1

    meta = {
        "site": site,
        "base_iri": str(ex),
        "brick_mapping_version": mapping_version(),
        "rows_in": len(rows),
        "rows_skipped_schema_invalid": skipped,
        "files": {
            stem: {
                "points": c["points"],
                "equipment": len(c["equipment"]),
                "systems": len(c["systems"]),
                "triples": len(graphs[stem]),
            }
            for stem, c in sorted(counts.items())
        },
    }
    return graphs, meta


def main() -> int:
    configure_stdout_utf8()
    ap = argparse.ArgumentParser(
        description="Emit one Brick Turtle graph per building from decoded outputs."
    )
    ap.add_argument("--outputs", required=True,
                    help="decoded outputs jsonl (ideally outputs_linked.jsonl)")
    ap.add_argument("--site", required=True, help="site name, e.g. tasen")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--base-iri", help=f"IRI namespace (default {DEFAULT_BASE}<site>#)")
    args = ap.parse_args()

    rows = read_jsonl(args.outputs)
    graphs, meta = build_graphs(rows, args.site, args.base_iri)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for stem, g in sorted(graphs.items()):
        g.serialize(destination=str(out_dir / f"{stem}.ttl"), format="turtle")
    (out_dir / "emit_meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    total_points = sum(f["points"] for f in meta["files"].values())
    print(f"{len(graphs)} graph(s), {total_points} points "
          f"({meta['rows_skipped_schema_invalid']} rows skipped) -> {out_dir}")
    for stem, f in meta["files"].items():
        print(f"  {stem}.ttl: {f['points']} points · {f['equipment']} equipment · "
              f"{f['systems']} systems · {f['triples']} triples")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
