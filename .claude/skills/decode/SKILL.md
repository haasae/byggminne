---
name: decode
description: Cold-start decode of a batch of building labels into schema-conforming JSON, using a FRESH subagent per label (no paid API). Use when the user wants to decode a batch (data/eval/batches/<id>/input.jsonl) into runs/<id>/outputs.jsonl for scoring against gold. Honors the cold-start rule in docs/EVALUATION.md.
---

# /decode — subscription-mode batch decoder

Turn a batch of labels into `outputs.jsonl` by decoding **each label in its own
fresh subagent**. A fresh subagent = a stateless cold-start call: isolated
context, no memory of other labels, no access to gold. This is the subscription
substitute for an API call; the Python harness scores the result.

## Non-negotiable invariants (the cold-start rule)
- **One fresh subagent per label.** Never reuse a subagent across labels. Never
  put two labels, or any previous label's output, in the same subagent context.
- **The subagent sees only the frozen context pack + one label.** That whole
  prompt is produced by `prompt_builder`; do not add gold, hints, or worked
  examples. Corrections live in the KB (`knowledge_base/`), never in this prompt.
- **Between runs, only the KB/rules change.** Stamp `kb_version` so a metric move
  is attributable.

## Inputs
- `input` — path to `data/eval/batches/<batch_id>/input.jsonl` (rows of
  `{raw_label, source_type}`; no semantic fields).
- Pick `out_dir = runs/<batch_id>__<kb_version>` (compute `kb_version` in step 1).

## Procedure
0. **Deterministic layer FIRST (zero tokens).** Run:
   `python -m src.decode.deterministic_batch --input <input> --out-dir <out_dir>`
   This decodes everything rules + retrieval can handle and writes
   `outputs.jsonl` + `residue.jsonl` + `coverage.md`. **Only the rows in
   `residue.jsonl` proceed to the subagent steps below** (use it as the input,
   re-indexing from 0). If the residue is empty, skip to step 4. Report the
   coverage numbers to the user before spawning any subagents.
1. **Stamp the context.** Run:
   `python -m src.decode.context_pack --version`  → this is `kb_version`.
   Count rows in the residue (read the file). Decide `out_dir`.
2. **Decode each row i (0-based), ideally a few in parallel:**
   1. Build the self-contained prompt:
      `python -m src.decode.prompt_builder --input <input> --index <i>`
      Capture its stdout verbatim — that is the entire subagent task.
   2. Spawn a **fresh** subagent (Agent tool, subagent_type `general-purpose`)
      whose prompt is exactly that text. The subagent must return ONLY the JSON
      object (the prompt already instructs this).
   3. Save the returned text to `runs/<id>/raw/<i>.json` and validate it:
      `python -m src.validate.schema_validator --file runs/<id>/raw/<i>.json`
   4. **If invalid:** spawn a NEW fresh subagent with the same prompt plus the
      validator's error lines appended (mirror `build_retry_suffix`: a
      "the previous output was rejected, fix these problems" block). Max 2
      retries. This is a fresh stateless call, not a follow-up chat turn.
   5. **If still invalid after retries:** keep the raw object but mark it
      `{"schema_invalid": true, ...}` so it counts against the schema-validity
      rate. Never hand-fix it into a passing object.
3. **Assemble outputs.** APPEND the per-label JSON objects (one per line, with
   `"decode_method": "llm"`) to the deterministic `runs/<id>/outputs.jsonl`
   from step 0, and write `runs/<id>/run_meta.json` with:
   `{"model": "<the model you ran as>", "kb_version": "<hash>", "input": "<path>",
   "n": <count>, "schema_invalid": <count>}`.
4. **Score** (separate, deterministic step):
   `python -m src.score.run_score --outputs runs/<id>/outputs.jsonl
   --gold tests/gold/<batch_id>/gold.jsonl --out-dir runs/<id>`
   Then summarize `report.md` and the top entries in `errors.jsonl`.

## Notes
- Decoding N labels spawns N (+retries) subagents — expected. Parallelize in
  small groups; order does not matter (scoring aligns by `raw_label`).
- The future API path (`src/decode/run_batch.py`) automates steps 1–3 once an
  `anthropic` key exists; it produces the same `outputs.jsonl`, so gold and the
  scorer are unchanged.
