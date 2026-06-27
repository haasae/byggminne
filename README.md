# label-decoder

Decode unstructured building-energy measurement labels into a structured,
machine-readable format.

A "label" is a column header / point name from a building data system — an
unstructured (mostly Norwegian) string encoding building, system, subsystem,
component, and measurement type. This project interprets those names and
cross-checks them against the measurement data to produce structured output.

See `CLAUDE.md` for the full architecture, domain rules, and cross-check logic.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate   # optional
pip install -r requirements.txt
```

Always read CSVs as UTF-8 (Norwegian æ/ø/å). On Windows:
`PYTHONIOENCODING=utf-8`.

Put your data into data/raw

If you wish to add your own documents to give context to the LLM, add them to `docs/`. Then turn them to .md-files however you want and add to `docs_md`. The purpose of this is that it is easier for the LLM to understand the context if it is given as .md-files instead of PDF's.

## Layout

- `schema/decoded_label.schema.json` — the output contract every decoded label
  must validate against.
- `examples/` — three worked instances (clean Kiona, derived Kiona cost, redacted
  BACnet point).
- `data/raw/` — real building CSVs.  `data/synthetic/` — invented, structure-true
  samples for safe development.
- `src/` — extract (Layer 1), decode (Layer 2), profile (data cross-checks),
  validate.
- `knowledge_base/` — grows over time with validated mappings.
- `review/` — local human-in-the-loop review tool (later).

## Validate the examples

```bash
python src/validate/validate_examples.py
```

## Status

Current round: get the data we have into a structured format. Status may change
as external advisers clarify the data — keep `CLAUDE.md` updated.
