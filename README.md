# label-decoder

## Short intro of the application

### Motivation

This application is made on behalf of Oslobygg in the City of Oslo. It is part of a bigger project with the goal of providing operations personell with a way to visually observe where there is potential for energy-flexibility in the buildings that Oslobygg manage.

### Pipeline

This codebase creates a pipeline that does the following:
1. Decodes unstructured building-energy measurement labels into a structured, machine-readable format.
2. Translates structured labels into Brick Schema-format.
3. Creates a knowledge graph from the Brick Schema-code to be used in flexibility calculations.

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
   not always easy. `docs/PDF-to-Markdown.md` collects notes on it (work in
   progress), and `src/PDF-parser/` has two optional helper scripts
   (`pip install pymupdf`).
3. Extract the unique labels from your CSVs and build a decoder batch:
   `python -m src.extract.unique_labels data/raw/<file>.csv -o labels.txt`, then
   `python -m src.extract.build_batch labels.txt --source-type bacnet -o data/eval/batches/<id>/input.jsonl`.
4. Decode and evaluate with `python -m src.eval.run_eval --batch <id>` (see
   Quick start). Labels the deterministic layer can't handle land in a
   `residue.jsonl` for the LLM layer — see next section.

### The LLM layer

The deterministic layer (rules + retrieval) is plain Python and needs no LLM.
The residue, which is the labels it can't resolve, is decoded by the `/decode` skill (and
thin decodes enriched by `/enrich`), which ship in `.claude/skills/` and run
inside [Claude Code](https://claude.com/claude-code): one fresh subagent per
label, no paid API needed. `docs/EVALUATION.md` documents the cold-start rules
this must honor. An API-based runner (`src/decode/run_batch.py`) exists as a
blueprint but is not yet implemented.

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
│   ├── validate/                  # schema validation
│   ├── common/                    # shared IO/token helpers
│   └── PDF-parser/                # optional PDF→Markdown side tools (pymupdf)
├── tests/                         # pytest suite + gold sets (tests/gold/<id>/)
├── docs/                          # evaluation guide, output explainer, conversion notes
└── .claude/skills/                # /decode and /enrich — the LLM leg (Claude Code)
```

## License

Apache-2.0 — see `LICENSE`.

## Status

Work in progress as of 21.07.2026.
