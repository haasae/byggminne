"""Phase 4a: parse COLLECTiEF ontologies -> committed zone-location index JSONs.

Reads each B0X_ontology.ttl and extracts Zone -> Level -> SubBuilding from
the rec:isPartOf spatial hierarchy. Output JSONs are small and committed so
graph_enrich.py works without the 65 GB dataset present.

    python -m src.heating.ontology_join [--root ...] [--out-dir ...]
"""
import argparse
import json
import sys
from pathlib import Path

from rdflib import Graph, Namespace, RDF, RDFS

REC = Namespace('https://w3id.org/rec#')


def _local(node):
    s = str(node)
    return s.split('#')[-1] if '#' in s else s.rsplit('/', 1)[-1]


def parse_building(ttl_path):
    """Parse one building ontology TTL -> index dict.

    Returns {building, building_node, building_name, zones: {zone_id: {
        level_id, level_label, sub_building_id, sub_building_label}}}.
    Zones not linked to a Level are silently skipped (they'll get a
    location_missing flag in the graph).
    """
    g = Graph()
    g.parse(str(ttl_path), format='turtle')

    types = {}
    for s, p, o in g.triples((None, RDF.type, None)):
        types.setdefault(_local(s), set()).add(_local(o))

    labels = {}
    for s, p, o in g.triples((None, RDFS.label, None)):
        labels[_local(s)] = str(o)

    is_part_of = {}
    for s, p, o in g.triples((None, REC.isPartOf, None)):
        is_part_of[_local(s)] = _local(o)

    site = next((k for k, v in types.items() if 'Site' in v), None)
    building_node = next((k for k, v in types.items() if 'Building' in v), None)

    zones = {}
    for node, parent in is_part_of.items():
        if 'Level' not in types.get(parent, set()):
            continue
        sub = is_part_of.get(parent)
        zones[node] = {
            'level_id': parent,
            'level_label': labels.get(parent, parent),
            'sub_building_id': sub,
            'sub_building_label': labels.get(sub, sub) if sub else None,
        }

    return {
        'building': site,
        'building_node': building_node,
        'building_name': labels.get(building_node, building_node),
        'zones': zones,
    }


def main(argv=None):
    from src.common.io_utils import configure_stdout_utf8
    configure_stdout_utf8()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', default=str(Path('knowledge_base') / 'incoming'))
    ap.add_argument('--out-dir', default=str(Path('knowledge_base') / 'collectief_index'))
    ap.add_argument('--buildings', help='comma list (default: all)')
    args = ap.parse_args(argv)

    root = Path(args.root)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    want = set(args.buildings.split(',')) if args.buildings else None
    for ttl in sorted((root / 'Buildings').glob('*/B*_ontology.ttl')):
        bid = ttl.parent.name
        if want and bid not in want:
            continue
        result = parse_building(ttl)
        out = out_dir / f'{bid}.json'
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'{bid}: {len(result["zones"])} zones -> {out}')

    return 0


if __name__ == '__main__':
    sys.exit(main())
