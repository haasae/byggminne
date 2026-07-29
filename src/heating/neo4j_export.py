"""Phase 4 extra: export enriched heating data as a Cypher import file for Neo4j.

Maps the enriched graph to a property graph:
  - Nodes:   Site, Building, SubBuilding, Level, Zone, Room, Point, Meter,
             System (all with human-readable names + descriptions)
  - Edges:   (Zone|Room)-[:LOCATED_IN]->(Level)-[:PART_OF]->(SubBuilding)
             -[:PART_OF]->(Building)-[:PART_OF]->(Site), HAS_POINT,
             SUBMETER_OF/METERS, System PART_OF/LOCATED_IN/SERVES

Zone nodes carry all derived facts as properties so they can be filtered and
explored directly in Neo4j Browser without traversing extra nodes.

Hand-curated facts may carry provenance in the index JSON under a top-level
"provenance" key:

    "provenance": {"<entity-id>": {"<fact>": {"source": "...",
                                              "confidence": "verified"}}}

Facts: 'location' (placement edges), 'serves' (SERVES edges), 'heating'
(heatingType on SubBuilding/Room; room entries may carry a 'value' that
overrides the inherited type — resolves mixed buildings per room; a
'conflict': true on a sub-building surfaces the warning in the node
description), 'number' (resolved Room numbers).
Confidence scale: 'verified' (value-checked or explicit BMS text/names),
'curated' (human reading of UI graphics/layout), 'assumed' (inherited).
Rooms inheriting heatingType from their sub-building without room-level
evidence are stamped 'assumed' automatically.

Usage:
    python -m src.heating.neo4j_export
    # -> runs/heating/neo4j_import.cypher

In Neo4j Browser (after creating a blank database):
    :source <path-to-cypher-file>
  or paste the file content and run.

Then explore with:
    MATCH (n) RETURN n LIMIT 100
    MATCH (z:Zone {heatingType: 'electric-fast'}) RETURN z
    MATCH p=(z:Zone)-[:LOCATED_IN*..4]->(s:Site) RETURN p LIMIT 50
"""
import argparse
import json
import re
import sys
from pathlib import Path

from src.common.io_utils import configure_stdout_utf8, read_jsonl

DEFAULT_INDEX_DIR = Path('knowledge_base') / 'collectief_index'
DEFAULT_RUNS_DIR = Path('runs') / 'heating'
DEFAULT_OUT = Path('runs') / 'heating' / 'neo4j_import.cypher'

# Norwegian display names for room point signals (graph readability).
SIGNAL_NAMES = {
    'temperature': 'Temperatur',
    'temperature_setpoint': 'Settpunkt temperatur',
    'setpoint_command': 'Settpunkt (kommandert)',
    'heating': 'Varmepådrag',
    'co2': 'CO2',
    'presence': 'Tilstedeværelse (PIR)',
    'airflow': 'Luftmengde',
}

SIGNAL_DESCS = {
    'temperature': 'Temperaturføler – målt romtemperatur (°C).',
    'temperature_setpoint': 'Settpunkt – ønsket romtemperatur (°C).',
    'setpoint_command': 'Kommandert settpunkt skrevet via Modbus (°C).',
    'heating': 'Varmepådrag 0–100 % – hvor mye varme rommet får akkurat nå.',
    'co2': 'CO2-måler – luftkvalitet (ppm).',
    'presence': 'Tilstedeværelsessensor (PIR) – om rommet er i bruk.',
    'airflow': 'Luftmengdemåler – tilluft til rommet.',
}

# NS 3457-8 component letters, verified in
# knowledge_base/komponentkodeliste_dir/komponentkodeliste.md (row cited).
COMPONENT_DESCS = {
    'RT': 'Temperaturgiver',               # row 574
    'RD': 'Differansetrykkgiver',          # row 558
    'RP': 'Trykkgiver',                    # row 570
    'LR': 'Frekvensomformer',              # row 412
    'SB': 'Motorstyrt reguleringsventil',  # row 588
}
# First digit of a 3-digit component number encodes the side (row 574).
SIDE_DIGIT = {'4': 'tilluft/tur', '5': 'fraluft/retur'}

UTILITY_NAMES = {'district_heating': 'fjernvarme'}


def _component_desc(code):
    """Plain-language description for an NS 3457-8 point code.

    Only verified letter codes get a meaning (never invent); the side digit
    is applied only to the documented 3-digit form (RT401), not SB47-style.
    """
    m = re.match(r'([A-Z]{2})(\d{3})(?:[_.]|$)', code)
    if m and m.group(1) in COMPONENT_DESCS:
        base = COMPONENT_DESCS[m.group(1)]
        side = SIDE_DIGIT.get(m.group(2)[0])
        return f'{base}, {side} ({code}).' if side else f'{base} ({code}).'
    m = re.match(r'([A-Z]{2})', code)
    if m and m.group(1) in COMPONENT_DESCS:
        return f'{COMPONENT_DESCS[m.group(1)]} ({code}).'
    return f'Signal fra BMS-en ({code}).'


def _system_desc(s):
    kind = s.get('kind', '')
    if kind == 'ahu':
        d = ('Ventilasjonsaggregat – maskinen som leverer og trekker ut '
             'luft for en del av skolen.')
        if s.get('subsystem'):
            d += f" NS-systemnummer {s['subsystem']}."
        if s.get('controller'):
            d += f" Styres av undersentral {s['controller']}."
        return d
    if kind == 'heating':
        if s.get('parent'):
            return ('Varmekrets – gren av det vannbårne varmeanlegget som '
                    'forsyner ett bygg med radiatorvarme.')
        return ('Vannbårent varmeanlegg – hovedsystemet som fordeler varme '
                f"til radiatorene (NS-system {s.get('subsystem', '')}).")
    if kind == 'device':
        return 'Teknisk enhet lest fra BMS-en.'
    return 'Teknisk system fra BMS-en.'


def _esc(v):
    """Escape a string value for Cypher."""
    return str(v).replace("\\", "\\\\").replace("'", "\\'")


def _prov_rel(prov, ent_id, fact):
    """Relationship variable + SET suffix for a provenance-stamped edge.

    Returns ('', '') when the index carries no provenance for this fact, so
    callers can format unconditionally: f"-[{var}:SERVES]->(b){suffix};".
    """
    p = (prov.get(ent_id) or {}).get(fact) or {}
    sets = [f"r.{k} = '{_esc(p[k])}'"
            for k in ('source', 'confidence') if p.get(k)]
    return ('r', ' SET ' + ', '.join(sets)) if sets else ('', '')


def _load_runs(runs_dir):
    def by_zone(path):
        out = {}
        if Path(path).exists():
            for r in read_jsonl(path):
                out[(r['building'], r['zone'])] = r
        return out

    return {
        'zone_table': by_zone(runs_dir / 'zone_table.jsonl'),
        'regimes':    by_zone(runs_dir / 'regimes.jsonl'),
        'ht':         by_zone(runs_dir / 'heating_types.jsonl'),
        'tau':        by_zone(runs_dir / 'step_summary.jsonl'),
        'orient':     by_zone(runs_dir / 'orientation.jsonl'),
    }


def generate_cypher(index_dir, runs_dir):
    data = _load_runs(runs_dir)
    lines = [
        "// Auto-generated by src/heating/neo4j_export.py",
        "// Run in Neo4j Browser against a blank database.",
        "",
        "// ── Constraints (idempotent re-run) ──────────────────────────────────",
        "CREATE CONSTRAINT site_id IF NOT EXISTS FOR (n:Site) REQUIRE n.id IS UNIQUE;",
        "CREATE CONSTRAINT building_id IF NOT EXISTS FOR (n:Building) REQUIRE n.id IS UNIQUE;",
        "CREATE CONSTRAINT subbuilding_id IF NOT EXISTS FOR (n:SubBuilding) REQUIRE n.id IS UNIQUE;",
        "CREATE CONSTRAINT level_id IF NOT EXISTS FOR (n:Level) REQUIRE n.id IS UNIQUE;",
        "CREATE CONSTRAINT zone_id IF NOT EXISTS FOR (n:Zone) REQUIRE n.id IS UNIQUE;",
        "CREATE CONSTRAINT point_id IF NOT EXISTS FOR (n:Point) REQUIRE n.id IS UNIQUE;",
        "CREATE CONSTRAINT meter_id IF NOT EXISTS FOR (n:Meter) REQUIRE n.id IS UNIQUE;",
        "CREATE CONSTRAINT system_id IF NOT EXISTS FOR (n:System) REQUIRE n.id IS UNIQUE;",
        "CREATE CONSTRAINT room_id IF NOT EXISTS FOR (n:Room) REQUIRE n.id IS UNIQUE;",
        "",
        "// ── Spatial skeleton ─────────────────────────────────────────────────",
    ]

    # Collect all spatial nodes across all building indexes
    sites, buildings, subbuildings, levels = {}, {}, {}, {}
    sub_heating = {}  # sub_building id -> verified heating type (radiator/...)
    prov = {}     # entity id -> fact -> {source, confidence} (hand-curated)
    meters = []   # (meter dict, building_node id)
    systems = []  # (system dict, building_node id)
    rooms = []    # (room dict, building_node id)

    for idx_path in sorted(index_dir.glob('*.json')):
        idx = json.loads(idx_path.read_text(encoding='utf-8'))
        site_id = idx.get('building')
        bld_id = idx.get('building_node')
        # display_name may hold Norwegian characters (content, not identifier)
        bld_name = idx.get('display_name') or idx.get('building_name') or bld_id
        prov.update(idx.get('provenance', {}))

        if site_id and site_id not in sites:
            sites[site_id] = True
            lines.append(
                f"MERGE (n:Site {{id: '{_esc(site_id)}'}}) "
                f"SET n.name = '{_esc(bld_name)}', n.label = '{_esc(site_id)}', "
                f"n.description = 'Toppnode for {_esc(bld_name)}. "
                f"Kort stedskode: {_esc(site_id)}.';")

        if bld_id and bld_id not in buildings:
            buildings[bld_id] = site_id
            lines.append(
                f"MERGE (n:Building {{id: '{_esc(bld_id)}'}}) "
                f"SET n.name = '{_esc(bld_name)}', n.site = '{_esc(site_id or '')}', "
                f"n.description = 'Skolen {_esc(bld_name)}. Bygg, rom, tekniske "
                f"systemer og energimålere ligger under denne.';")

        # Known sub-buildings from a building survey/index, even without any
        # zone placement: context nodes; the PART_OF loop links them to the
        # Building.
        for sb in idx.get('sub_buildings', []):
            if sb['id'] not in subbuildings:
                subbuildings[sb['id']] = bld_id
                props = [f"n.name = '{_esc(sb['name'])}'"]
                desc = 'Enkeltbygg/bygningsdel på skolens tomt.'
                if sb.get('heating'):
                    sub_heating[sb['id']] = sb['heating']
                    props.append(f"n.heatingType = '{_esc(sb['heating'])}'")
                    desc += f" Vannbåren varme: {sb['heating']}."
                    hp = (prov.get(sb['id']) or {}).get('heating') or {}
                    for k, pn in (('source', 'heatingSource'),
                                  ('confidence', 'heatingConfidence')):
                        if hp.get(k):
                            props.append(f"n.{pn} = '{_esc(hp[k])}'")
                    # known source conflict -> warn in the description
                    # itself, not only in the click-panel provenance
                    if hp.get('conflict'):
                        props.append('n.heatingConflict = true')
                        desc += (' NB: kildene er i konflikt om varmetypen'
                                 ' - se heatingSource.')
                props.append(f"n.description = '{_esc(desc)}'")
                lines.append(
                    f"MERGE (n:SubBuilding {{id: '{_esc(sb['id'])}'}}) "
                    f"SET {', '.join(props)};")

        for m in idx.get('meters', []):
            meters.append((m, bld_id))
        for s in idx.get('systems', []):
            systems.append((s, bld_id))
        for r in idx.get('rooms', []):
            rooms.append((r, bld_id))

        for zone_id, loc in idx.get('zones', {}).items():
            sub_id = loc.get('sub_building_id')
            sub_label = loc.get('sub_building_label') or sub_id
            lev_id = loc.get('level_id')
            lev_label = loc.get('level_label') or lev_id

            if sub_id and sub_id not in subbuildings:
                subbuildings[sub_id] = bld_id
                lines.append(
                    f"MERGE (n:SubBuilding {{id: '{_esc(sub_id)}'}}) "
                    f"SET n.name = '{_esc(sub_label)}', "
                    f"n.description = 'Enkeltbygg/bygningsdel på skolens tomt.';")

            if lev_id and lev_id not in levels:
                levels[lev_id] = sub_id
                lines.append(
                    f"MERGE (n:Level {{id: '{_esc(lev_id)}'}}) "
                    f"SET n.label = '{_esc(lev_label)}', "
                    f"n.description = 'Etasje (plan). Grupperer rom og soner "
                    f"på samme plan.';")

    # Spatial relationships
    lines += ["", "// ── Spatial relationships ───────────────────────────────────────────"]
    for bld_id, site_id in buildings.items():
        if site_id:
            lines.append(
                f"MATCH (a:Building {{id:'{_esc(bld_id)}'}}), (b:Site {{id:'{_esc(site_id)}'}}) "
                f"MERGE (a)-[:PART_OF]->(b);")
    for sub_id, bld_id in subbuildings.items():
        if bld_id:
            lines.append(
                f"MATCH (a:SubBuilding {{id:'{_esc(sub_id)}'}}), (b:Building {{id:'{_esc(bld_id)}'}}) "
                f"MERGE (a)-[:PART_OF]->(b);")
    for lev_id, sub_id in levels.items():
        if sub_id:
            lines.append(
                f"MATCH (a:Level {{id:'{_esc(lev_id)}'}}), (b:SubBuilding {{id:'{_esc(sub_id)}'}}) "
                f"MERGE (a)-[:PART_OF]->(b);")

    # Energy meters (from the index files; hierarchy = parent references).
    # Rest meters (computed remainders) are not in the indexes on purpose.
    if meters:
        lines += ["", "// ── Energy meters ───────────────────────────────────────────────────"]
        for m, _bld in meters:
            kind = 'sub' if m.get('parent') else 'main'
            utility = m.get('utility', '')
            utility_no = UTILITY_NAMES.get(utility, utility)
            mdesc = (f'Hovedmåler for {utility_no} – toppen av målerhierarkiet.'
                     if kind == 'main' else
                     f'Undermåler for {utility_no} – måler en del av forbruket.')
            lines.append(
                f"MERGE (m:Meter {{id: '{_esc(m['id'])}'}}) "
                f"SET m.name = '{_esc(m['name'])}', m.kind = '{kind}', "
                f"m.utility = '{_esc(utility)}', "
                f"m.description = '{_esc(mdesc)}';")
        for m, bld_id in meters:
            if m.get('parent'):
                lines.append(
                    f"MATCH (a:Meter {{id:'{_esc(m['id'])}'}}), (b:Meter {{id:'{_esc(m['parent'])}'}}) "
                    f"MERGE (a)-[:SUBMETER_OF]->(b);")
            elif bld_id:
                lines.append(
                    f"MATCH (m:Meter {{id:'{_esc(m['id'])}'}}), (b:Building {{id:'{_esc(bld_id)}'}}) "
                    f"MERGE (m)-[:METERS]->(b);")

    # Technical systems (controllers / heating branches / devices) and their
    # component points -- the raw-label component hierarchy (e.g. Tåsen).
    if systems:
        lines += ["", "// ── Technical systems and component points ──────────────────────────"]
        sys_ids = {s['id'] for s, _ in systems}

        # Ungrouped AHUs would hang directly off the Building and visually
        # compete with the SubBuildings -> collect them under one
        # "Ventilasjon" category node per building.
        vent_cats = {}
        for s, bld_id in systems:
            if s.get('kind') == 'ahu' and not s.get('parent') \
                    and not s.get('sub_building_id') and bld_id:
                vent_cats[bld_id] = f'{bld_id}-VENTILASJON'
        for bld_id, cat_id in vent_cats.items():
            lines.append(
                f"MERGE (s:System {{id: '{_esc(cat_id)}'}}) "
                f"SET s.kind = 'category', s.name = 'Ventilasjon', "
                f"s.description = 'Samlenode for skolens "
                f"ventilasjonsaggregater.';")
            lines.append(
                f"MATCH (a:System {{id:'{_esc(cat_id)}'}}), "
                f"(b:Building {{id:'{_esc(bld_id)}'}}) "
                f"MERGE (a)-[:PART_OF]->(b);")

        for s, bld_id in systems:
            props = [f"s.kind = '{_esc(s.get('kind', ''))}'",
                     f"s.name = '{_esc(s.get('name') or s['id'])}'",
                     f"s.description = '{_esc(_system_desc(s))}'"]
            for key, prop in (('controller', 'controller'),
                              ('subsystem', 'subsystem')):
                if s.get(key):
                    props.append(f"s.{prop} = '{_esc(s[key])}'")
            lines.append(
                f"MERGE (s:System {{id: '{_esc(s['id'])}'}}) "
                f"SET {', '.join(props)};")
            sub_id = s.get('sub_building_id')
            lv, lset = _prov_rel(prov, s['id'], 'location')
            if s.get('parent') and s['parent'] in sys_ids:
                lines.append(
                    f"MATCH (a:System {{id:'{_esc(s['id'])}'}}), "
                    f"(b:System {{id:'{_esc(s['parent'])}'}}) "
                    f"MERGE (a)-[{lv}:PART_OF]->(b){lset};")
            elif sub_id and sub_id in subbuildings:
                # data-backed placement (e.g. IK001 -> Bygg 5)
                lines.append(
                    f"MATCH (a:System {{id:'{_esc(s['id'])}'}}), "
                    f"(b:SubBuilding {{id:'{_esc(sub_id)}'}}) "
                    f"MERGE (a)-[{lv}:LOCATED_IN]->(b){lset};")
            elif s.get('kind') == 'ahu' and bld_id in vent_cats:
                lines.append(
                    f"MATCH (a:System {{id:'{_esc(s['id'])}'}}), "
                    f"(b:System {{id:'{_esc(vent_cats[bld_id])}'}}) "
                    f"MERGE (a)-[{lv}:PART_OF]->(b){lset};")
            elif bld_id:
                lines.append(
                    f"MATCH (a:System {{id:'{_esc(s['id'])}'}}), "
                    f"(b:Building {{id:'{_esc(bld_id)}'}}) "
                    f"MERGE (a)-[{lv}:PART_OF]->(b){lset};")
            serves = s.get('serves')
            if isinstance(serves, str):
                serves = [serves]
            sv_var, sv_set = _prov_rel(prov, s['id'], 'serves')
            for sv in serves or []:
                if sv in subbuildings:
                    # from the branch label (320001_bygg5) or hand-curated
                    # serve-lists (UI plant page kurs names)
                    lines.append(
                        f"MATCH (a:System {{id:'{_esc(s['id'])}'}}), "
                        f"(b:SubBuilding {{id:'{_esc(sv)}'}}) "
                        f"MERGE (a)-[{sv_var}:SERVES]->(b){sv_set};")
            for p in s.get('points', []):
                pid = f"{s['id']}_{p['code']}"
                lines.append(
                    f"MERGE (p:Point {{id: '{_esc(pid)}'}}) "
                    f"SET p.code = '{_esc(p['code'])}', "
                    f"p.name = '{_esc(p['code'])}', "
                    f"p.description = '{_esc(_component_desc(p['code']))}', "
                    f"p.label = '{_esc(p['label'])}', "
                    f"p.file = '{_esc(p.get('file', ''))}';")
                lines.append(
                    f"MATCH (s:System {{id:'{_esc(s['id'])}'}}), "
                    f"(p:Point {{id:'{_esc(pid)}'}}) "
                    f"MERGE (s)-[:HAS_POINT]->(p);")

    # Rooms (from raw room-sensor labels) and their points.
    if rooms:
        lines += ["", "// ── Rooms and room sensor points ────────────────────────────────────"]
        for r, bld_id in rooms:
            number = r.get('number', '')
            sigs = {p['signal'] for p in r.get('points', [])}
            props = [f"r.name = 'Rom {_esc(number)}'",
                     f"r.number = '{_esc(number)}'",
                     f"r.bus = '{_esc(r.get('bus', ''))}'"]
            for key in ('bygg', 'floor', 'address', 'plan'):
                if r.get(key) is not None:
                    props.append(f"r.{key} = {r[key]}")
            # The flexibility triple, spelled out per component (y / r / u)
            for sig, prop in (('temperature', 'hasTemperature'),
                              ('temperature_setpoint', 'hasSetpoint'),
                              ('heating', 'hasHeating')):
                props.append(f"r.{prop} = {str(sig in sigs).lower()}")
            for key in ('triple', 'metasys'):
                if r.get(key) is not None:
                    props.append(f"r.{key} = {str(bool(r[key])).lower()}")
            if r.get('source'):
                props.append(f"r.source = '{_esc(r['source'])}'")
            # heating type: room-level provenance beats the sub-building
            # inheritance (which is honestly stamped 'assumed'); a 'value'
            # in the room entry resolves mixed buildings per room
            rp = (prov.get(r['id']) or {}).get('heating') or {}
            htype = rp.get('value') or sub_heating.get(r.get('sub_building_id'))
            if htype:
                props.append(f"r.heatingType = '{_esc(htype)}'")
                src = rp.get('source') or \
                    f"Arvet fra bygget ({r['sub_building_id']})."
                conf = rp.get('confidence') or 'assumed'
                props.append(f"r.heatingSource = '{_esc(src)}'")
                props.append(f"r.heatingConfidence = '{_esc(conf)}'")
            np_ = (prov.get(r['id']) or {}).get('number') or {}
            for k, pn in (('source', 'numberSource'),
                          ('confidence', 'numberConfidence')):
                if np_.get(k):
                    props.append(f"r.{pn} = '{_esc(np_[k])}'")
            sig_list = ', '.join(
                SIGNAL_NAMES[k] for k in ('temperature', 'temperature_setpoint',
                                          'setpoint_command', 'heating', 'co2',
                                          'presence', 'airflow') if k in sigs)
            rdesc = f'Rom {number} med romstyring fra BMS-en.'
            if sig_list:
                rdesc += f' Signaler: {sig_list}.'
            props.append(f"r.description = '{_esc(rdesc)}'")
            lines.append(
                f"MERGE (r:Room {{id: '{_esc(r['id'])}'}}) "
                f"SET {', '.join(props)};")
            sub_id = r.get('sub_building_id')
            floor = r.get('floor', r.get('plan'))
            if sub_id and sub_id in subbuildings and floor is not None:
                # Group rooms by floor: Room -> Level -> SubBuilding
                lev_id = f"{sub_id}-PLAN{floor}"
                if lev_id not in levels:
                    levels[lev_id] = sub_id
                    # floor digit 0 = underetasje; the BMS's own schedule
                    # naming calls it U1 (e.g. Bygg1-2_PlanU1)
                    lev_label = 'U1' if floor == 0 else f'Plan {floor}'
                    lines.append(
                        f"MERGE (n:Level {{id: '{_esc(lev_id)}'}}) "
                        f"SET n.label = '{lev_label}', "
                        f"n.description = 'Etasje (plan). Grupperer rom og "
                        f"soner på samme plan.';")
                    lines.append(
                        f"MATCH (a:Level {{id:'{_esc(lev_id)}'}}), "
                        f"(b:SubBuilding {{id:'{_esc(sub_id)}'}}) "
                        f"MERGE (a)-[:PART_OF]->(b);")
                lines.append(
                    f"MATCH (r:Room {{id:'{_esc(r['id'])}'}}), "
                    f"(l:Level {{id:'{_esc(lev_id)}'}}) "
                    f"MERGE (r)-[:LOCATED_IN]->(l);")
            elif sub_id and sub_id in subbuildings:
                lines.append(
                    f"MATCH (r:Room {{id:'{_esc(r['id'])}'}}), "
                    f"(sb:SubBuilding {{id:'{_esc(sub_id)}'}}) "
                    f"MERGE (r)-[:LOCATED_IN]->(sb);")
            elif bld_id:
                lines.append(
                    f"MATCH (r:Room {{id:'{_esc(r['id'])}'}}), "
                    f"(b:Building {{id:'{_esc(bld_id)}'}}) "
                    f"MERGE (r)-[:LOCATED_IN]->(b);")
            seen_sig = {}
            for p in r.get('points', []):
                # WISE rooms have several points per signal (e.g. airflow) —
                # suffix duplicates so they stay distinct Point nodes
                n = seen_sig[p['signal']] = seen_sig.get(p['signal'], 0) + 1
                pid = f"{r['id']}_{p['signal']}" + (f"_{n}" if n > 1 else '')
                # Human name: keep the BMS one (WISE); else build from signal
                pname = p.get('name') or \
                    f"Rom {number} {SIGNAL_NAMES.get(p['signal'], p['signal'])}"
                pdesc = SIGNAL_DESCS.get(p['signal'], 'Målepunkt fra BMS-en.')
                pprops = [f"p.name = '{_esc(pname)}'",
                          f"p.description = '{_esc(pdesc)}'",
                          f"p.signal = '{_esc(p['signal'])}'",
                          f"p.label = '{_esc(p['label'])}'",
                          f"p.file = '{_esc(p.get('file', ''))}'"]
                if p.get('metasys_id'):
                    pprops.append(f"p.metasys_id = '{_esc(p['metasys_id'])}'")
                if p.get('trended') is not None:
                    pprops.append(f"p.trended = {str(bool(p['trended'])).lower()}")
                lines.append(
                    f"MERGE (p:Point {{id: '{_esc(pid)}'}}) "
                    f"SET {', '.join(pprops)};")
                lines.append(
                    f"MATCH (r:Room {{id:'{_esc(r['id'])}'}}), "
                    f"(p:Point {{id:'{_esc(pid)}'}}) "
                    f"MERGE (r)-[:HAS_POINT]->(p);")

    # Zone nodes
    lines += ["", "// ── Zone nodes (with all derived facts as properties) ───────────────"]

    # Load all indexes into a zone->loc dict
    zone_loc = {}
    for idx_path in sorted(index_dir.glob('*.json')):
        idx = json.loads(idx_path.read_text(encoding='utf-8'))
        for zone_id, loc in idx.get('zones', {}).items():
            zone_loc[zone_id] = loc

    t_triple_zones = sorted(
        (b, z) for (b, z), row in data['zone_table'].items()
        if row.get('kind') == 't_triple'
    )

    for building, zone_id in t_triple_zones:
        key = (building, zone_id)
        props = {'id': zone_id, 'building': building,
                 'csvFile': f'Thermal zone/{zone_id}.csv',
                 'description': ('Termisk sone med tidsserier for settpunkt, '
                                 'temperatur og varmepådrag (CSV-fila under '
                                 'csvFile).')}

        r = data['regimes'].get(key)
        if r:
            props['regime'] = r['regime']

        o = data['orient'].get(key)
        if o:
            props['orientation'] = o['orientation']
            props['winterDutyPct'] = o['winter_duty']
            props['summerDutyPct'] = o['summer_duty']

        ht = data['ht'].get(key)
        if ht:
            props['heatingType'] = ht['verdict']
            props['confidence'] = ht['confidence']
            props['reasoning'] = ht['reasoning']

        tau = data['tau'].get(key)
        if tau and tau.get('minutes_to_1k'):
            med = tau['minutes_to_1k'].get('median')
            if med is not None:
                props['tauMedianMin'] = int(med)

        zt = data['zone_table'].get(key, {})
        flags = zt.get('flags', [])
        if flags:
            props['qualityFlags'] = ','.join(flags)

        # Build SET clause
        set_parts = []
        for k, v in props.items():
            if isinstance(v, str):
                set_parts.append(f"z.{k} = '{_esc(v)}'")
            elif isinstance(v, bool):
                set_parts.append(f"z.{k} = {str(v).lower()}")
            else:
                set_parts.append(f"z.{k} = {v}")

        lines.append(
            f"MERGE (z:Zone {{id: '{_esc(zone_id)}'}}) SET {', '.join(set_parts)};")

    # Point nodes: the bound triple (setpoint r / sensor y / actuator u).
    # The graph carries the POINTER to the time series (file + column);
    # the values themselves stay in the CSVs (layer-4 rule: values join by ID).
    lines += ["", "// ── Points (setpoint / sensor / actuator per zone) ──────────────────"]
    _POINTS = [
        ("setpoint", "Setpoint", "T_Setvalue", "r", "degC",
         "Settpunkt", "Ønsket temperatur (r) – tidsserie i CSV-fila."),
        ("sensor",   "Sensor",   "T_Actualvalue", "y", "degC",
         "Temperatur", "Målt romtemperatur (y) – tidsserie i CSV-fila."),
        ("actuator", "Actuator", "T_Gain", "u", "percent",
         "Varmepådrag", "Varmepådrag 0–100 % (u) – tidsserie i CSV-fila."),
    ]
    for building, zone_id in t_triple_zones:
        csv_file = f"Buildings/{building}/Thermal zone/{zone_id}.csv"
        for role, label, column, signal, unit, name_no, desc in _POINTS:
            pid = f"{zone_id}_{role}"
            lines.append(
                f"MERGE (p:Point:{label} {{id: '{_esc(pid)}'}}) "
                f"SET p.role = '{role}', p.signal = '{signal}', "
                f"p.name = '{_esc(name_no)}', "
                f"p.description = '{_esc(desc)}', "
                f"p.column = '{column}', p.unit = '{unit}', "
                f"p.file = '{_esc(csv_file)}';")
    lines += ["", "// ── Zone -> Point relationships ─────────────────────────────────────"]
    for building, zone_id in t_triple_zones:
        for role, *_rest in _POINTS:
            pid = f"{zone_id}_{role}"
            lines.append(
                f"MATCH (z:Zone {{id:'{_esc(zone_id)}'}}), (p:Point {{id:'{_esc(pid)}'}}) "
                f"MERGE (z)-[:HAS_POINT]->(p);")

    # Zone -> Level relationships
    lines += ["", "// ── Zone location relationships ─────────────────────────────────────"]
    for building, zone_id in t_triple_zones:
        loc = zone_loc.get(zone_id)
        zv, zset = _prov_rel(prov, zone_id, 'location')
        if loc and loc.get('level_id'):
            lev_id = loc['level_id']
            lines.append(
                f"MATCH (z:Zone {{id:'{_esc(zone_id)}'}}), (l:Level {{id:'{_esc(lev_id)}'}}) "
                f"MERGE (z)-[{zv}:LOCATED_IN]->(l){zset};")
        elif loc and loc.get('sub_building_id'):
            # placement known to sub-building level only (e.g. Skøyen AHU
            # dekningsområde panels), no level yet
            lines.append(
                f"MATCH (z:Zone {{id:'{_esc(zone_id)}'}}), "
                f"(sb:SubBuilding {{id:'{_esc(loc['sub_building_id'])}'}}) "
                f"MERGE (z)-[{zv}:LOCATED_IN]->(sb){zset};")
        elif loc and loc.get('building_node'):
            # No level or sub-building placement known for this zone --
            # attach it to its Building so the graph stays connected.
            bn = loc['building_node']
            lines.append(
                f"MATCH (z:Zone {{id:'{_esc(zone_id)}'}}), (b:Building {{id:'{_esc(bn)}'}}) "
                f"MERGE (z)-[{zv}:LOCATED_IN]->(b){zset};")
        else:
            lines.append(
                f"// WARNING: no location index for {zone_id}")
        if loc and loc.get('meter_id'):
            lines.append(
                f"MATCH (z:Zone {{id:'{_esc(zone_id)}'}}), "
                f"(m:Meter {{id:'{_esc(loc['meter_id'])}'}}) "
                f"MERGE (z)-[:MEASURED_BY]->(m);")

    return '\n'.join(lines) + '\n'


def main(argv=None):
    configure_stdout_utf8()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--index-dir',
                    default=str(DEFAULT_INDEX_DIR))
    ap.add_argument('--runs-dir', default=str(DEFAULT_RUNS_DIR))
    ap.add_argument('-o', '--out', default=str(DEFAULT_OUT))
    args = ap.parse_args(argv)

    cypher = generate_cypher(Path(args.index_dir), Path(args.runs_dir))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(cypher, encoding='utf-8')
    line_count = cypher.count('\n')
    print(f'{line_count} lines -> {out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
