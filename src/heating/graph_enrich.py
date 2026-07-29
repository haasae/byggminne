"""Phase 4b: emit one enriched Turtle graph per building.

Reads:
  - knowledge_base/collectief_index/B0X.json  (spatial skeleton from ontology_join)
  - runs/heating/zone_table.jsonl              (kind, flags)
  - runs/heating/regimes.jsonl                 (gain regime)
  - runs/heating/heating_types.jsonl           (verdict, confidence, reasoning)
  - runs/heating/step_summary.jsonl            (tau)
  - runs/heating/orientation.jsonl             (heating/cooling/dual/idle)

Emits runs/heating/graphs/B0X.ttl -- one enriched Turtle graph per building
with three content tiers:
  1. Spatial skeleton  (Zone -> Level -> SubBuilding -> Building -> Site)
  2. Bound triple      (sensor / setpoint / actuator with ref:hasTimeseriesId)
  3. Our derived facts (heating type, regime, tau, orientation, quality flags)

    python -m src.heating.graph_enrich [--index-dir ...] [--runs-dir ...] [--out-dir ...]
"""
import argparse
import json
import sys
from pathlib import Path

from rdflib import XSD, Graph, Literal, Namespace, RDF, RDFS, URIRef

from src.common.io_utils import configure_stdout_utf8, read_jsonl

BLDG = Namespace('urn:example#')
BRICK = Namespace('https://brickschema.org/schema/1.4/Brick#')
REC = Namespace('https://w3id.org/rec#')
REF = Namespace('https://brickschema.org/schema/Brick/ref#')
HLAB = Namespace('urn:hlab#')


def _load_runs(runs_dir):
    """Load all run data -> dicts keyed (building, zone)."""
    def _by_zone(path):
        out = {}
        if Path(path).exists():
            for r in read_jsonl(path):
                out[(r['building'], r['zone'])] = r
        return out

    return {
        'zone_table': _by_zone(runs_dir / 'zone_table.jsonl'),
        'regimes': _by_zone(runs_dir / 'regimes.jsonl'),
        'heating_types': _by_zone(runs_dir / 'heating_types.jsonl'),
        'step_summary': _by_zone(runs_dir / 'step_summary.jsonl'),
        'orientation': _by_zone(runs_dir / 'orientation.jsonl'),
    }


def _add_spatial(g, index, added_nodes):
    """Add Tier 1 spatial skeleton triples from index dict."""
    site_id = index.get('building')
    building_node = index.get('building_node')
    building_name = index.get('building_name')

    if site_id and site_id not in added_nodes:
        s = BLDG[site_id]
        g.add((s, RDF.type, REC.Site))
        g.add((s, RDFS.label, Literal(site_id)))
        added_nodes.add(site_id)

    if building_node and building_node not in added_nodes:
        b = BLDG[building_node]
        g.add((b, RDF.type, REC.Building))
        g.add((b, RDFS.label, Literal(building_name or building_node)))
        if site_id:
            g.add((b, REC.isPartOf, BLDG[site_id]))
        added_nodes.add(building_node)

    for zone_id, loc in index.get('zones', {}).items():
        level_id = loc['level_id']
        sub_id = loc['sub_building_id']

        if sub_id and sub_id not in added_nodes:
            sub = BLDG[sub_id]
            g.add((sub, RDF.type, REC.SubBuilding))
            g.add((sub, RDFS.label, Literal(loc['sub_building_label'] or sub_id)))
            if building_node:
                g.add((sub, REC.isPartOf, BLDG[building_node]))
            added_nodes.add(sub_id)

        if level_id and level_id not in added_nodes:
            lev = BLDG[level_id]
            g.add((lev, RDF.type, REC.Level))
            g.add((lev, RDFS.label, Literal(loc['level_label'] or level_id)))
            if sub_id:
                g.add((lev, REC.isPartOf, BLDG[sub_id]))
            added_nodes.add(level_id)

        if zone_id not in added_nodes:
            z = BLDG[zone_id]
            g.add((z, RDF.type, REC.Zone))
            g.add((z, RDFS.label, Literal(zone_id)))
            if level_id:
                g.add((z, REC.isPartOf, BLDG[level_id]))
            added_nodes.add(zone_id)


def _add_zone(g, building, zone_id, csv_rel_path, data, loc_known):
    """Add Tier 2 (bound triple) and Tier 3 (derived facts) for one zone."""
    z = BLDG[zone_id]

    if not loc_known:
        g.add((z, RDF.type, REC.Zone))
        g.add((z, RDFS.label, Literal(zone_id)))
        g.add((z, HLAB.locationMissing, Literal(True)))

    # Tier 2: bound triple - sensor / setpoint / actuator
    for suffix, brick_type, ts_id in [
        ('_sensor', BRICK.Temperature_Sensor, 'T_Actualvalue'),
        ('_setpoint', BRICK.Temperature_Setpoint, 'T_Setvalue'),
        ('_actuator', BRICK.Valve_Position_Command, 'T_Gain'),
    ]:
        pt = BLDG[zone_id + suffix]
        g.add((pt, RDF.type, brick_type))
        g.add((pt, BRICK.isPointOf, z))
        bn = URIRef(f'urn:ts:{zone_id}{suffix}')
        g.add((pt, REF.timeseries, bn))
        g.add((bn, REF.hasTimeseriesId, Literal(ts_id)))
        g.add((bn, REF.storedAt, Literal(csv_rel_path)))

    key = (building, zone_id)

    # Tier 3: gain regime
    regime_row = data['regimes'].get(key)
    if regime_row:
        g.add((z, HLAB.gainRegime, Literal(regime_row['regime'])))

    # Tier 3: orientation
    orient_row = data['orientation'].get(key)
    if orient_row:
        g.add((z, HLAB.orientation, Literal(orient_row['orientation'])))
        g.add((z, HLAB.winterDutyPct,
               Literal(orient_row['winter_duty'], datatype=XSD.decimal)))
        g.add((z, HLAB.summerDutyPct,
               Literal(orient_row['summer_duty'], datatype=XSD.decimal)))

    # Tier 3: heating type verdict
    ht_row = data['heating_types'].get(key)
    if ht_row:
        g.add((z, HLAB.heatingType, Literal(ht_row['verdict'])))
        g.add((z, HLAB.heatingTypeConfidence,
               Literal(ht_row['confidence'], datatype=XSD.decimal)))
        g.add((z, HLAB.heatingTypeReasoning, Literal(ht_row['reasoning'])))

    # Tier 3: tau from step summary
    tau_row = data['step_summary'].get(key)
    if tau_row and tau_row.get('minutes_to_1k'):
        median = tau_row['minutes_to_1k'].get('median')
        if median is not None:
            g.add((z, HLAB.tauMedianMin,
                   Literal(int(median), datatype=XSD.integer)))

    # Tier 3: quality flags
    zt_row = data['zone_table'].get(key)
    if zt_row:
        for flag in zt_row.get('flags', []):
            g.add((z, HLAB.qualityFlag, Literal(flag)))


def emit_building(building, index, data, out_path):
    """Build and write the enriched graph for one building."""
    g = Graph()
    g.bind('bldg', BLDG)
    g.bind('brick', BRICK)
    g.bind('rec', REC)
    g.bind('ref', REF)
    g.bind('hlab', HLAB)
    g.bind('rdfs', RDFS)

    added_nodes = set()
    _add_spatial(g, index, added_nodes)

    # All T-triple zones for this building
    t_triple_zones = {
        zone_id for (b, zone_id), row in data['zone_table'].items()
        if b == building and row.get('kind') == 't_triple'
    }

    loc_zone_ids = set(index.get('zones', {}).keys())

    for zone_id in sorted(t_triple_zones):
        csv_rel_path = f'Thermal zone/{zone_id}.csv'
        loc_known = zone_id in loc_zone_ids
        if not loc_known and zone_id not in added_nodes:
            pass  # _add_zone handles it
        _add_zone(g, building, zone_id, csv_rel_path, data, loc_known)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    g.serialize(destination=str(out_path), format='turtle')
    return len(g)


def main(argv=None):
    configure_stdout_utf8()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--index-dir',
                    default=str(Path('knowledge_base') / 'collectief_index'))
    ap.add_argument('--runs-dir', default=str(Path('runs') / 'heating'))
    ap.add_argument('--out-dir',
                    default=str(Path('runs') / 'heating' / 'graphs'))
    ap.add_argument('--buildings', help='comma list (default: all)')
    args = ap.parse_args(argv)

    index_dir = Path(args.index_dir)
    runs_dir = Path(args.runs_dir)
    out_dir = Path(args.out_dir)

    data = _load_runs(runs_dir)
    want = set(args.buildings.split(',')) if args.buildings else None

    buildings = {(b, z) for b, z in data['zone_table']}
    all_buildings = sorted({b for b, _ in buildings})

    for building in all_buildings:
        if want and building not in want:
            continue
        index_path = index_dir / f'{building}.json'
        if index_path.exists():
            with open(index_path, encoding='utf-8') as fh:
                index = json.load(fh)
        else:
            index = {'building': building, 'building_node': None,
                     'building_name': None, 'zones': {}}
            print(f'{building}: no index JSON, spatial skeleton will be missing')

        out = out_dir / f'{building}.ttl'
        n = emit_building(building, index, data, out)
        print(f'{building}: {n} triples -> {out}')

    return 0


if __name__ == '__main__':
    sys.exit(main())
