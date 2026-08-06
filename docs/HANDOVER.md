# Handover — operating and extending the building knowledge graphs

Written 2026-07-30 for the team taking custody of this application (Oslobygg).
The current maintainer leaves the project in early August 2026. This document
is the operational entry point: what exists, what you must receive besides
this repository, how to regenerate the delivered graphs, how to add a new
building, and the one verification job that must wait for the heating season.

It links to existing documentation instead of repeating it:
`README.md` (setup, the label-decode pipeline), `docs/ROOM_HEATING_PLAN.md`
(the room-heating flexibility pipeline, phase by phase), and the module
docstrings in `src/heating/` (each states its inputs, outputs, and CLI).
The Norwegian user manuals are the friendly front doors:
`docs/BRUKERVEILEDNING_GRAF.md` (read the graph — for operations) and
`docs/BRUKERVEILEDNING_PIPELINE.md` (build a graph — for the technical
operator).

## 1. What is delivered

- **The label-decode pipeline** — unstructured BMS point names → structured,
  schema-validated objects → Brick. See `README.md`.
- **The room-heating flexibility pipeline** (`src/heating/`) — per-zone gain
  regime, energy proxy, step-response time constants, heating-type verdicts,
  and an enriched knowledge graph per building. Developed and validated on the
  COLLECTiEF dataset (7 Ålesund buildings). See `docs/ROOM_HEATING_PLAN.md`.
- **Two production knowledge graphs**: Tåsen skole and Skøyen skole — spatial
  skeleton (site → building → floor → room), systems with placement and
  serves-relations, per-room heating points, heating types with per-fact
  provenance (`verified` / `curated` / `assumed`). Imported into Neo4j from
  generated Cypher.
- **Three buildings pending**: Bislett Stadion, Margarinfabrikken barnehage,
  Furuseth Hageby. Their BMS front-end is Piscada (GK); no data received yet.
  Section 4 is the playbook for building their graphs.

## 2. This repository is public — you also need the local bundle

Building-specific and copyrighted material is deliberately **not in git**
(see `.gitignore`). Custody transfer = this repository **plus** the local
bundle below, handed over directly. Without it, the school graphs cannot be
regenerated.

| What | Paths | Why local |
|---|---|---|
| Building indexes (the graph source of truth) | `knowledge_base/index/` (every `*.json` — `TA.json`, `SK.json`, `BI.json`, … — plus `OPEN_ITEMS.md`) | building-specific |
| Building surveys + provenance narratives | `knowledge_base/tasen_building_survey.md`, `knowledge_base/skoyen_building_survey.md`, `knowledge_base/meter_hierarchies.md`, `docs/images/`, `docs/fjernvarmemaalere_skoler.html` | building-specific |
| Deployment adapters + their tests | `src/extract/metasys_dump.py`, `src/extract/metasys_crawl.js`, `src/extract/metasys_room_probe.js`, `src/heating/{metasys_rooms,metasys_join,tasen_index,skoyen_extract}.py`, `tests/test_metasys_*.py`, `tests/test_heating_{metasys_rooms,metasys_join,tasen_index,skoyen_extract}.py` | our schools' BMS specifics |
| Metasys crawl data | `knowledge_base/incoming/metasys/` | building-specific |
| NS 3451 / NS 3457-8 markdown | `knowledge_base/NS-3451_dir/`, `knowledge_base/NS-3457_dir/` | copyrighted (Standard Norge) — licensee must supply own copy |
| COLLECTiEF dataset + derived index | `knowledge_base/incoming/` (65 GB), `knowledge_base/collectief_index/`, `knowledge_base/collectief_survey.md` | size; regenerable from the dataset (CC BY 4.0) |
| Raw building CSVs | `data/raw/`, `data/training/` | building-specific |
| Secrets | `.env` (`NEO4J_PASSWORD`) | do **not** transfer — set your own |

`runs/` is regenerable output; no need to transfer.

## 3. Regenerating the school graphs (Tåsen + Skøyen)

Prerequisites: Python + `pip install -r requirements.txt`; a local Neo4j
instance at `bolt://127.0.0.1:7687`; `NEO4J_PASSWORD` in the environment or a
`.env` file in the repo root.

```bash
# Only if raw point/room data changed — regenerate the generated index keys
# (hand-curated keys in TA.json/SK.json are preserved on regeneration):
python -m src.heating.tasen_index          # TA systems+rooms from raw BMS exports
python -m src.heating.metasys_rooms        # parse the Metasys crawl
python -m src.heating.metasys_join         # join room data into SK.json/TA.json

# Export + import:
python -m src.heating.neo4j_export --index-dir knowledge_base/index \
    --runs-dir runs/timeseries -o runs/heating/index.cypher
python -m src.heating.neo4j_import --cypher runs/heating/index.cypher
```

`runs/timeseries/` holds the converted per-zone trend CSVs plus the data-derived
facts (regimes, step summaries, heating-type verdicts) for both schools; it is
fully regenerable via the extractors + pipeline in section 5. The export picks
those facts up automatically: they land on Zone nodes (system zones) and, for
zones whose id matches an index Room, on the Room node as `regime`,
`dataVerdict`, `dataConfidence`, `dataReasoning` and `qualityFlags` properties
— the curated `heatingType` (with its provenance) is never overwritten by a
data verdict.

The index JSON structure, the provenance format, and the confidence scale
(`verified` / `curated` / `assumed`) are documented in the
`src/heating/neo4j_export.py` docstring. Read it before editing an index.

## 4. Adding a new building (Bislett / Margarinfabrikken / Furuseth)

The pattern proven on Tåsen and Skøyen — skeleton and survey first, point
data joins later:

1. **Get BMS access.** For these three: Piscada (GK's SCADA front-end, runs
   in a VM like Metasys). Down and reported to the supplier as of 2026-07-30.
2. **Survey the BMS UI.** Sub-buildings, floors, rooms; plants and AHUs with
   their placement panels; per room the heating triple — temperature sensor,
   setpoint, heating actuator/gain. Write a survey markdown (pattern:
   `tasen_building_survey.md`) with screenshots. Record *how you know* each
   fact — that becomes provenance.
3. **Create `knowledge_base/index/<CODE>.json`** following `TA.json` /
   `SK.json`: hand-curated keys (`building`, `display_name`, `comment`,
   `provenance`, `sub_buildings`, `system_locations`, `system_serves`,
   `room_numbers`, `controller_subsystems`) plus generated keys (`systems`,
   `rooms`) if machine-readable exports exist.
4. **Write an adapter only if exports exist.** Point-list adapter pattern:
   `tasen_index.py`; trend-CSV adapter pattern: `skoyen_extract.py`. Adapters
   are deployment-specific and stay local; never bake building specifics into
   the source-agnostic core.
5. **Export + import** as in section 3 — `neo4j_export` picks up every
   `*.json` in `--index-dir`.
6. **Verify with data** once trend series exist: section 5.

## 5. Winter verification runbook (heating season, ~November 2026)

Room heating *equipment* was verified visually in the BMS (radiators in every
room-controlled room at Tåsen; Skøyen surveyed room by room), but the
*response class* (electric-fast vs hydronic-slow vs floor-slow) and the rooms
still marked `assumed` need heating-season data. The maintainer will not be
on the project then — this section is the recipe.

1. **Arrange setback events.** Step-response mining needs setpoint drops. As
   of July 2026 Tåsen rooms hold 21/21 °C around the clock (no night
   setback), so there are **no events to mine**. Ask drift to schedule a
   temporary night-setback (e.g. one week, −2 K or more) on the rooms in
   question — or confirm setbacks have since been enabled.
2. **Make sure setpoints are exported.** The 2025 Tåsen export contains the
   heating actuator for 94 rooms and the temperature for 43, but a setpoint
   for only **one** room (adr106). Ask for per-room setpoints to be trended
   and included in the export — without them, setback events cannot be
   detected even if drift schedules them.
3. **Export winter trends** per room: room temperature, setpoint, heating
   actuator/gain (the 2025 exports sample roughly every 10 minutes; that
   works — the converters pad the grid).
4. **Convert and run.** This exact chain was rehearsed 2026-07-30 on the
   2025 data:

   ```bash
   python -m src.heating.skoyen_extract     # SK long-format export -> runs/timeseries
   python -m src.heating.tasen_extract      # TA OS001 export -> runs/timeseries (index-driven)
   python -m src.heating.build_zone_table --root runs/timeseries --buildings SK,TA \
       -o runs/timeseries/zone_table.jsonl --cache runs/timeseries/scan_cache.jsonl
   python -m src.heating.gain_regime runs/timeseries/zone_table.jsonl \
       -o runs/timeseries/regimes.jsonl
   python -m src.heating.step_response --root runs/timeseries --buildings SK,TA \
       --events-dir runs/timeseries/events --summary runs/timeseries/step_summary.jsonl \
       --report runs/timeseries/step_response_report.md --force
   python -m src.heating.heating_type runs/timeseries/regimes.jsonl \
       runs/timeseries/step_summary.jsonl -o runs/timeseries/heating_types.jsonl
   ```

   For a new export file, pass `--input` to the extractor (see each module's
   docstring). `tasen_extract` is index-driven: it reads the room point
   labels from `TA.json`, so it survives label-format changes as long as the
   index is regenerated first (section 3).
5. **Read the verdicts.** Thresholds live in
   `knowledge_base/heating_rules.json`: electric ≤ 90 min to a 1 K drop,
   hydronic ≥ 240 min, floor heating ≥ 50 % of events with no 1 K drop,
   minimum 10 usable events per zone.
6. **Write results back**: update the `provenance` entries in
   `TA.json`/`SK.json` (`assumed` → `verified`, resolve any
   `conflict: true` flags), then regenerate and reimport (section 3). The
   raw data verdicts also flow into the graph automatically as `dataVerdict`
   properties on the Room nodes.

## 6. Open items at handover

The concrete ledger — including which rooms are still `assumed`, the
Bygg 3/5 circuit-naming conflict, and the pending FDV documentation
request — is building-specific and therefore lives in the local bundle:
`knowledge_base/index/OPEN_ITEMS.md`.

## 7. Quick prerequisites recap

- Python 3, `pip install -r requirements.txt`; on Windows set
  `PYTHONIOENCODING=utf-8` and always read/write UTF-8 (Norwegian æ/ø/å).
- Neo4j (Desktop or server) at `bolt://127.0.0.1:7687`, password via
  `NEO4J_PASSWORD` env var or `.env`.
- The local bundle from section 2.
