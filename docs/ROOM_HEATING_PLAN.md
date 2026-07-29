# Room-heating pivot — development plan

*Written 2026-07-22, after the pivot meeting and the COLLECTiEF survey
(`knowledge_base/collectief_survey.md`). Produced by a 3-candidate plan
competition (data-first / ontology-first / flexibility-first) judged by a
3-lens panel; data-first won unanimously; the best ideas and every shared
blind spot the panel found are folded in below.
Amended 2026-07-23: deliverable format settled with the energy-flexibility
co-worker — an **enriched knowledge graph** per building (see Phase 4), with
human-readable views generated from it.*

> **Status (2026-07-29):** Phases 0–4 are DONE for COLLECTiEF — the zone
> table, regimes, energy proxies, step-response taus (the pre-registered
> electric-vs-hydronic prediction CONFIRMED, see
> `knowledge_base/data_observations.md`), heating-type verdicts, and the
> enriched per-building graphs all exist and are tested. Two deviations from
> the plan below: (1) `collectief_zone_types.jsonl` was never created — the
> classification store is the run outputs (`runs/heating/zone_table.jsonl`
> et al.); (2) `src/heating/` grew beyond the module list with the
> Tåsen/Skøyen transfer work (BMS index generation, Metasys room extraction,
> Neo4j graph export — see CLAUDE.md §9). The transfer section's "decision
> point" has been taken: structural transfer is done; per-room flexibility
> numbers for our own schools await heating-season timeseries.

## Context

The project narrowed scope: **room heating only** — the sensor / setpoint /
actuator-gain triple at room level — with the end goal of mapping **energy
flexibility** per room. The advisor's mail
(`knowledge_base/incoming/NOTES_about_ontology.md`) defines the exercise:
identify the triple, map it to heating equipment types, model location, and
use response speed (electric fast, waterborne slow) to characterize systems.
The COLLECTiEF dataset provides 784 room-heating triples across 7 buildings
with reference ontologies — but the survey proved the ontologies' actuator
typing is boilerplate, so **heating type per zone must be inferred from the
data**. That inference is our core contribution and this plan's spine.

**Guiding principle (the winning bet):** one streamed pass over the 784
T-triple zone CSVs into a canonical per-zone table — with gain-regime and
thermal-response classification validated against building metadata priors,
weather, and (where electric) meters — delivers flexibility insight faster
than any graph work. Graph work comes last: the ontology join attaches
location, then we emit enriched graphs carrying the verified facts.
Pure deterministic streaming + data cross-checks; **no LLM anywhere in this
plan.**

## New module: `src/heating/`

Source-agnostic core: every analysis module consumes a generic
`(timestamp, actual, setpoint, gain)` iterator + a zone-metadata dict.
`collectief_adapter.py` is **the only file that knows COLLECTiEF exists**.

```
src/heating/
├── collectief_adapter.py   # folder-with-space, header dispatch, onsets, padded grid, scan cache
├── triple_stats.py         # streaming per-zone accumulator (Welford pattern from src/profile/series_stats.py)
├── build_zone_table.py     # CLI driver -> runs/heating/zone_table.jsonl (+ .csv mirror)
├── gain_regime.py          # binary / modulating / mixed / dead, thresholds from knowledge_base/heating_rules.json
├── energy_proxy.py         # hourly duty cycle (binary) / mean position (modulating), coverage reported alongside
├── validate_regimes.py     # priors + weather + meter cross-checks (see Phase 2)
├── step_response.py        # setpoint-step natural experiments -> tau proxies
├── heating_type.py         # per-zone hypothesis: electric-fast / hydronic-slow / floor-slow / ambiguous
├── ontology_join.py        # location from B0X_ontology.ttl via committed index JSONs (rdflib, read-only)
├── graph_enrich.py         # emit one enriched Turtle graph per building (the deliverable)
└── flexibility.py          # per-zone flexibility indicators + ranking
```

Plus: `knowledge_base/heating_rules.json` (all thresholds/rules — editable
when advisor docs arrive, never hardcoded), `knowledge_base/
collectief_zone_types.jsonl` (accumulating classification store, with a CC BY
4.0 attribution header note), `tests/fixtures/collectief_mini/` (fabricated
~200-row dataset reproducing every landmine) and one test module per source
module. CI stays green with **zero** access to the 65 GB.

## Phases

### Phase 0 — Ground-truthing (half a day, do first)

The panel's unanimous blind-spot findings; each is cheap and de-risks
everything downstream.

1. **Timing benchmark:** stream ONE building (B07, smallest) end to end;
   measure rows/sec and check OneDrive hydration behavior + free disk
   (placeholders inflate on first read). Extrapolate and record the expected
   full-fleet wall-clock in the plan-tracking issue before committing to it.
2. **Timezone/DST verification** (the survey says "treat as UTC, verify" —
   this settles it): histogram setpoint step times-of-day across a DST
   transition. BMS setback schedules run in local wall-clock time, so if
   timestamps are UTC the steps must shift by exactly 1 h at each CET/CEST
   boundary; if they don't, timestamps are local. Do the same for weather
   (irradiance peak ≈ 11:00 UTC solar noon for Aalesund). Everything in
   Phases 2–4 (occupied-hours filters, step mining) depends on this answer.
3. **Advisor checkpoint:** the deliverable *format* is settled (2026-07-23,
   with the flexibility co-worker): an enriched knowledge graph per building,
   from which users extract what they need. Remaining ask for the advisor:
   any specific content wishes beyond the Phase 4 tiers, and the new docs
   expected "soon" — ask now.

*Verification:* a written note in `knowledge_base/data_observations.md` with
the timezone verdict + measured throughput.

### Phase 1 — Adapter + canonical zone table (the foundation)

Stream every zone CSV once; one row per zone: building, zone id, header kind,
real data window, post-onset coverage, triple stats (T range, setpoint
discrete levels + step count, gain histogram: %at-0 / %at-100 / interior,
k/n-average counts), dead flag, **comfort-deviation stats (T_Actualvalue −
T_Setvalue distribution — free in the same pass, and it is both a data-quality
screen and the comfort baseline every flexibility claim needs)**, and a
**stuck-sensor screen on T_Actualvalue** (variance/step-count — a frozen
sensor must not survive into tau fitting).

Mechanics: dispatch on **header, never filename**; scan cache keyed on
`(path, size, mtime)` for file-granular resumability; `--buildings` filter so
the first full pass is a 2-building smoke run (B07 electric vs B02 hydronic,
~5 GB) before the fleet pass; B03's coarser late-window cadence handled by
coverage math (per-window row counts, not grid assumptions).

*Verification:* hermetic pytest on the mini fixture; then on real data a
`check_survey_counts` subcommand asserts the survey's measured facts: 784
T-triples split 244/18/65/214/78/133/32, dead zones B07-MA-A-1-12/-13 and
B06-MA-A-1-13 flagged, orphan B01-MA-A-B-3.csv classified by its COOL header.

### Phase 2 — Gain regimes + energy proxy, triple-validated

Classify each zone's gain: **binary** (≈98%+ rows at exactly 0/100 after
unmasking k/n resampling averages 50/33.33/66.67), **modulating** (large
interior mass, ~10³ distinct values; never threshold on ==100 — B01 saturates
at 99), **mixed/uncertain** (honest middle class), **dead**. Energy proxy per
regime: hourly duty cycle (binary) / hourly mean position (modulating), always
with coverage alongside (39–46% missing makes bare means misleading).

Three independent validation channels, with the gate discipline the panel
demanded:

- **Pinned regressions (hard-fail):** the survey's individually measured
  zones must reproduce — B01-MA-A-1-21 modulating (~63% interior), the three
  dead zones dead, B04 showing both regimes.
- **Priors (warn-level, not hard-fail):** per-building regime distributions
  vs metadata (B01 majority-modulating, B05/B07 overwhelmingly binary…). The
  survey sampled only 3 zones/building — an unsampled modulating B05 zone is
  a *finding to record*, not a failure. Metadata is itself a hypothesis
  (name-is-hypothesis applies to metadata too; B03's "el. boiler +
  decentralized radiators" is ambiguous) — contradictions get logged to
  `data_observations.md`, never suppressed.
- **Physics:** heating-season duty cycle vs outdoor temperature
  (`Weather/weather.csv` air temp; Pearson approach reused from
  `src/profile/seasonal_check.py`) must correlate negatively — sign, not
  magnitude, is the criterion. Plus **meter cross-check** for the
  all-electric buildings only (B03/B05/B07: building-summed duty cycle vs
  `main` kWh daily), respecting the meter quirks (B02/B07 DD/MM/YYYY +
  unnamed column; liveness from 31/12/2022; B06 excluded — district heat
  never crosses the electric meter; B01 excluded — PV/HP submeter mix).

**Operational definitions (so the checks are specified, not vibes):**
*heating season* = calendar months Oct–Apr AND daily-mean outdoor temp <
12 °C; *occupied hours* = rows where the zone's setpoint equals its dominant
(modal) level, i.e. not at the 10/14 °C setback levels. Both live in
`heating_rules.json`.

*Verification:* `validate_regimes` exits 0 on pinned + physics checks;
warn-level report for priors; findings appended to `data_observations.md`.

### Phase 3 — Step-response tau + heating-type hypothesis

The schedule-stepped setpoints (2–6 discrete levels, night/holiday setbacks)
are natural experiments. Detect events keyed on **setpoint change PLUS
observed gain shutoff** (in binary zones temperature doesn't track setpoint
tightly — setpoint-only windows mis-frame the decay). Per event: time-to-63%
proxy, initial drift slope; **bin drift rates (K/h) by outdoor temperature**;
model-free "minutes to drift 1 K" fallback when the first-order shape fails;
dispersion across repeated events is the tau-quality gate.

**Stationarity check (COLLECTiEF was an intervention project):** compute
regime and tau per heating season, not only pooled — a mid-dataset control
change must surface as a flagged instability, not silently mix regimes.

Then `heating_type.py`: regime + tau distribution + building prior →
per-zone hypothesis (electric-fast / hydronic-slow / floor-slow / ambiguous)
with calibrated confidence + reasoning string (the project's output-contract
discipline, §5). **Pre-registered prediction** (advisor's): electric B05/B07
taus shorter than hydronic B01/B02 — the outcome goes to
`data_observations.md` *either way*; a negative result is a finding.

*Verification:* hermetic synthetic-series tests for the step detector and
classifiers; on real data, the pre-registered comparison report +
per-building tau tables in `runs/heating/step_response_report.md`.

### Phase 4 — Location join + enriched knowledge graph + flexibility ranking

Read-only rdflib parse of the 7 ontologies → small committed per-building
index JSONs (`knowledge_base/collectief_index/B0X.json`: zone → SubBuilding
MA/MO, Level, usage from metadata) with the survey's normalizations as a
named FIXUPS table; unresolved paths degrade to a flag list, never crash.
Source ontology classes are kept verbatim as provenance; our corrections
(actuator type) live only in our own fields — never silently rewrite.

**The deliverable: `graph_enrich.py` emits one Turtle graph per building** —
the generalized machine- and human-readable format settled with the
flexibility co-worker (2026-07-23); downstream users (dashboard, flexibility
calc) query/export from it themselves. Content, in priority order:

1. **Identity & location:** zone → Level → SubBuilding → Building spatial
   skeleton (from the source ontology via the index JSONs, provenance cited)
   with human-readable labels.
2. **The bound triple:** sensor / setpoint / actuator points on each zone,
   each keeping `ref:hasTimeseriesId` → CSV column. The graph *points at* the
   timeseries; it never contains them.
3. **Our derived facts (the value-add), in our own namespace:** heating-type
   verdict + calibrated confidence + reasoning, gain regime, tau estimate,
   energy-proxy method, dead/stuck quality flags. This is what COLLECTiEF's
   own ontologies cannot provide — a graph without these is a photocopy of
   their boilerplate and adds nothing.
4. Plant/circuit attribution: deferred (out of scope this round).

`flexibility.py` then ranks zones: heating type, tau, duty-cycle headroom,
comfort-deviation baseline, usage, location → `runs/heating/flexibility_map.md`
— a human view generated from the same facts the graph carries ("direct path
for flexibility: where it is, what characterizes the systems within the
rooms").

**Bounded B06-VAV experiment** (settles the survey's 133-vs-210 coverage
question): do the 77 VAV_Gain-only zones correlate negatively with winter
outdoor temp (district-heated AHU air = heating actuator?) — log the answer
either way, one afternoon, no scope creep.

*Verification:* index JSONs round-trip through rdflib; join coverage report;
emitted graphs parse with rdflib and list every T-triple zone with either
derived facts or an explicit exclusion reason; one graph spot-checked as a
Mermaid render via the existing `src/brick/graph_viz.py`; the flexibility map
lists every T-triple zone with either a ranking or an explicit exclusion
reason.

## Transfer to Tasen/Skøyen (decision point, not a phase)

Deferred deliberately: nobody has verified our own data even contains clean
room-level heating triples, and COLLECTiEF teaches us the signatures first.
Designed for from day one: the core takes generic iterators, and **one
hermetic end-to-end test runs the whole pipeline on a synthetic
NON-COLLECTiEF fixture building** — proof no dataset specifics leaked past
the adapter. After Phase 3: run the learned regime/tau signatures over
Tasen/Skøyen series grouped by `src/profile/relationship_check.py`; if
triples emerge, transfer is the next plan's Phase 1. The transfer vehicle is
`heating_rules.json` + `data_observations.md` — KB accumulation, per the
project's core principle.

## Out of scope (this round)

Live operation/dashboards; general label-decoding improvements (decode layer
frozen); CO2/COOL/VAV triples beyond inventory (except the bounded B06
experiment); duplicating COLLECTiEF's ontologies verbatim (our graphs carry
the spatial skeleton + our derived facts — an enrichment, not a re-print);
plant/circuit attribution graphs (B01 has zero zone→plant paths
anyway); zone-vs-room identity; full RC/grey-box models (time-to-63% proxy
until proven insufficient); meter timezone forensics beyond Phase 0's check;
any LLM involvement; PDF parser.

## Reuse map (verified to exist)

- `src/common/io_utils.py` — UTF-8 IO, jsonl helpers: used everywhere.
- `src/profile/series_stats.py` — Welford/capped-distinct streaming pattern:
  the template for `triple_stats.py`.
- `src/profile/seasonal_check.py` — Pearson-vs-reference: the weather check.
- `src/profile/relationship_check.py` — grouping for the transfer probe.
- rdflib (pinned already): `ontology_join.py` + `graph_enrich.py`. No new
  dependencies; pandas only if the streaming pass measurably fails (it
  shouldn't — I/O-bound).
- `src/brick/graph_viz.py` — Mermaid rendering of the enriched graphs.
- Untouched: `src/decode/`, `src/eval/`, `src/extract/`.

## Risks

| Risk | Mitigation |
|---|---|
| OneDrive hydration / disk on the 65 GB pass | Phase 0 benchmark; per-file scan cache; `--buildings` filter; recommend pinning Buildings local-only |
| Timestamps not UTC after all | Phase 0 DST check BEFORE any occupied-hours logic |
| Survey priors over-generalized (3 zones/bldg) | pinned-zone hard checks + warn-level distribution checks |
| Control changes mid-dataset | per-season stationarity split in Phase 3 |
| Advisor docs arrive and contradict rules | all thresholds/fixups in `heating_rules.json` + named FIXUPS table — one-line amendments |
| Missing-data bias in duty cycles | coverage reported beside every mean; no imputation, ever |

## Milestone 1 (one week, demonstrable)

Phase 0 + Phase 1 + Phase 2 core, first on the B07-vs-B02 smoke pair, then
the fleet: `build_zone_table` streams all 7 buildings; `validate_regimes`
passes pinned + physics checks; B01 classifies majority-modulating and
B05/B07 overwhelmingly binary **from signal shape alone**, matching the
electric-vs-hydronic reality of the buildings. Demonstrable to the advisor
as: *"here is every heating zone in your dataset, classified from data,
agreeing with what the buildings actually are."*
