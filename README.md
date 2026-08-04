# label-decoder

## Short intro of the application

### Motivation

This application is made on behalf of Oslobygg in the City of Oslo. It is part of a bigger project with the goal of providing operations personell with a way to visually observe where there is potential for energy-flexibility in the buildings that Oslobygg manage.

### Pipeline

This codebase creates a pipeline that does the following:
1. Decodes unstructured building-energy measurement labels into a structured, machine-readable format.
2. Translates structured labels into Brick Schema-format.
3. Creates a knowledge graph from the Brick Schema-code to be used in flexibility calculations.
4. Analyzes room-heating timeseries (`src/heating/`) to derive data-verified
   facts — gain regime, heating type, thermal response time, an energy proxy —
   and enriches the knowledge graph with them (Turtle per building, plus a
   Neo4j export). See `docs/ROOM_HEATING_PLAN.md` for the design and status.

A "label" is a point name from a building data system. More specifically, it's an
unstructured (mostly Norwegian) string encoding building, system, subsystem,
component, and measurement type.

See `CLAUDE.md` for the full architecture, domain rules, and cross-check logic.

## Who is this meant for

The project is meant to be used by those who wish to structure their building data to an understandable format. The main purpose is to provide functionality for Oslobygg, but hopefully it can be useful for others as well.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Always read CSVs as UTF-8 (Norwegian æ/ø/å). On Windows, set
`PYTHONIOENCODING=utf-8` before running scripts that print non-ASCII text.

**No building data ships with this repo** (`data/raw/` and `data/training/`
are gitignored). What *is* committed: evaluation batches of real labels under
`data/eval/batches/` and a gold set under `tests/gold/`, so you can run the
pipeline immediately — see Quick start.

## Quick start (no data needed)

```bash
# Decode one label:
python -m src.decode.try_label "360.001-RT401"

# Decode and score a committed batch against its gold set:
python -m src.eval.run_eval --batch b001

# Run the test suite:
python -m pytest -q

# Validate the worked examples against the schema:
python -m src.validate.validate_examples
```

`run_eval` decodes deterministically, scores against gold if
`tests/gold/<id>/gold.jsonl` exists, and writes a plain-language `summary.md`
under `runs/`. How to read the metrics honestly: `docs/EVALUATION.md`.

## How to use with your own data

1. Gather all info you can get about how your data is labeled and classified
   (tables, standards, vendor docs). Put the source documents in `docs/`.
2. Convert them to machine-readable Markdown and put each under
   `knowledge_base/<name>_dir/<name>.md`. This is where the decoder reads its
   reference material from. LLMs read Markdown far better than PDFs. This is
   not always easy; `src/PDF-parser/` has two optional helper scripts
   (`pip install pymupdf`).
3. Extract the unique labels from your CSVs and build a decoder batch:
   `python -m src.extract.unique_labels data/raw/<file>.csv -o labels.txt`, then
   `python -m src.extract.build_batch labels.txt --source-type bacnet -o data/eval/batches/<id>/input.jsonl`.
4. Decode and evaluate with `python -m src.eval.run_eval --batch <id>` (see
   Quick start). Labels the deterministic layer can't handle land in a
   `residue.jsonl` for the LLM layer — see next section.

### Surveying the building (BMS screenshots)

Decoded labels give structure, but a knowledge graph also needs facts that
often live only in the BMS user interface: which sub-buildings, floors and
rooms exist, which heating circuits and ventilation aggregates serve what,
and whether each room has the heating triple (temperature sensor, setpoint,
heating actuator). If the BMS offers no export or API, a **screenshot survey
of the UI is enough** — production graphs have been built that way. Capture,
in this order:

1. **Orientation** — the front page, the navigation tree fully expanded, and
   any site/building overview graphic with names on it.
2. **Heating** — the plant diagram; every circuit box zoomed until its name
   is readable (circuit names are the main evidence for heating type and for
   what each circuit serves); each circuit's detail page; pump-stop /
   outdoor-compensation settings; district-heating and hot-water pages.
3. **Ventilation** — each aggregate's page; zoom any placement/coverage
   panel (positions of buttons on overview maps are *not* trustworthy —
   panel text is).
4. **Room control** — floor/room overviews, then room detail pages showing
   the triple and the equipment graphic. One shot per page *style* is
   enough, but note how many rooms it represents — and take one example of a
   room with no heating controls, if any exist.
5. **Energy/meter pages**, if the UI has them.

Rules of thumb: navigate read-only (never touch setpoint fields, hand/auto
switches, or start/stop buttons); a zoomed, readable label beats pretty
framing; name files after the fact they prove. Store screenshots under a
gitignored path (e.g. `knowledge_base/incoming/<bms>/pics/<building>/`) —
they are building data and must never be committed. While surveying, record
*how* you know each fact (explicit panel text vs. your reading of a
graphic) — that distinction becomes the graph's per-fact provenance
(`verified` / `curated` / `assumed`). From the survey, write a survey
markdown and a building index; the playbook is `docs/HANDOVER.md` §4.

### The LLM layer

The deterministic layer (rules + retrieval) is plain Python and needs no LLM.
The residue, which is the labels it can't resolve, is decoded by the `/decode` skill (and
thin decodes enriched by `/enrich`), which ship in `.claude/skills/` and run
inside [Claude Code](https://claude.com/claude-code): one fresh subagent per
label, no paid API needed. `docs/EVALUATION.md` documents the cold-start rules
this must honor. An API-based runner (`src/decode/run_batch.py`) exists as a
blueprint but is not yet implemented.

Claude Code is the tested path, not a hard dependency. Other agentic tools
(e.g. OpenAI Codex) are oriented by `AGENTS.md` and can follow the same skill
procedures; plain chat LLMs (ChatGPT, Gemini, …) can decode via the
copy-paste harness `python -m src.decode.manual_batch` — see
`docs/BRUKERVEILEDNING_PIPELINE.md` ch. 7.

### NS standards (bring your own)

The decoder's reference material includes the Norwegian standards NS 3451 and
NS 3457-8. These are **copyrighted by Standard Norge and not distributed with
this repo**. If you own them, convert them to Markdown and place them at
`knowledge_base/NS-3451_dir/NS-3451.md` and
`knowledge_base/NS-3457_dir/NS-3457.md`. Without them everything still runs.
The decode context pack inserts an explicit "NOT AVAILABLE" stub instead
(`src/decode/context_pack.py`), but LLM decodes can't cite those standards.
The freely published TFM system-code list and component-code list *are*
included under `knowledge_base/`.

## Layout

```
label-decoder/
├── CLAUDE.md                      # full architecture, domain rules, decode grammar
├── schema/                        # decoded_label.schema.json — the output contract
├── examples/                      # three worked schema instances
├── data/
│   ├── raw/                       # your building CSVs (gitignored, ships empty)
│   ├── eval/batches/              # committed label batches (b001, b_all_tasen, b_all_skoyen)
│   ├── synthetic/                 # placeholder for invented samples
│   └── training/                  # local training excerpts (gitignored)
├── knowledge_base/                # decode rules, validated decodes, NS/TFM/Brick reference
├── src/
│   ├── extract/                   # Layer 1: pull unique labels out of a dataset
│   ├── decode/                    # Layer 2: rules + retrieval + enrichment + LLM merge
│   ├── profile/                   # data profiling + cross-checks + promotion to the KB
│   ├── score/                     # metrics, alignment, reports
│   ├── eval/                      # one-command decode → score → summary driver
│   ├── brick/                     # Brick mapping, Turtle graph emitter, readiness report
│   ├── heating/                   # room-heating flexibility pipeline (zone table, regimes, tau, graph enrichment, Neo4j export)
│   ├── validate/                  # schema validation
│   ├── common/                    # shared IO/token helpers
│   └── PDF-parser/                # optional PDF→Markdown side tools (pymupdf)
├── tests/                         # pytest suite + gold sets (tests/gold/<id>/) + synthetic fixtures
├── docs/                          # evaluation guide, output explainer, heating plan, parser analysis
└── .claude/skills/                # /decode and /enrich — the LLM leg (Claude Code)
```

## Documentation map

**User manuals (Norwegian — start here):**
- `docs/OPPLAERING_NYTT_BYGG.md` — the training walkthrough: from nothing to
  a finished knowledge graph for a new building, written for a non-developer
  (includes a session plan for whoever does the teaching).
- `docs/BRUKERVEILEDNING_GRAF.md` — for operations personnel: how to read
  and query the knowledge graph in Neo4j (no programming needed).
- `docs/BRUKERVEILEDNING_PIPELINE.md` — for the technical operator: what to
  feed the application and how to build a knowledge graph from your own data.

**Using the pipeline (read in this order):**
- `README.md` — this file: what it is, setup, quick start.
- `docs/HANDOVER.md` — operating the delivered graphs: regeneration, the
  add-a-building playbook, the winter verification runbook, local-only bundle.
- `docs/EVALUATION.md` — how decoding quality is measured; the cold-start rule.
- `docs/output_explainer.md` — how to read one decoded label (methods, confidence, tier).
- `schema/README.md` — the output contract, field by field (`examples/` has three worked instances).

**Design & findings:**
- `docs/ROOM_HEATING_PLAN.md` — the room-heating flexibility pipeline: plan, phases, status.
- `docs/tokenizer_failure_modes.md` — what the deterministic parser can't do and why.
- `knowledge_base/data_observations.md` — data-confirmed label facts (the "name = hypothesis, data = test" journal).

**Decoder reference (the LLM's context pack — humans welcome too):**
- `CLAUDE.md` — the project map: architecture, label grammar, cross-check rules.
- `knowledge_base/decode_rules.md` — decode rules and code enumerations.
- `knowledge_base/bacnet_sd_label_grammar.md` — positional grammar for BACnet/SD labels.
- `knowledge_base/komponentkodeliste_dir/`, `knowledge_base/TFM_systemkodeliste_dir/` — NS component/system code tables.
- `knowledge_base/control_number_area_map.md` — auto-generated controller→area lookup.
- Machine stores: `deterministic_rules.json`, `validated_decodes.jsonl`, `brick_mapping.json`, `heating_rules.json`.

**AI procedures:** `.claude/skills/decode/` and `.claude/skills/enrich/` — the LLM leg, run inside Claude Code.

Some reference material is local-only and not in this repo: the copyrighted NS
standards (see "NS standards" above) and building-specific surveys/indexes for
the pilot buildings.

## License

Apache-2.0 — see `LICENSE`.

## Status

Work in progress as of 30.07.2026.
