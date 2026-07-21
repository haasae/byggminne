---
name: enrich
description: LLM-enrich thin deterministic decodes selected by src/decode/enrichment.py, using a FRESH subagent per label (no paid API), then merge with the deterministic outputs. Use after `python -m src.decode.enrichment` produced an enrichment_residue.jsonl. Honors the cold-start rule in docs/EVALUATION.md.
---

# /enrich — subscription-mode enrichment decoder

Decode each label in `enrichment_residue.jsonl` in its **own fresh subagent**
and merge the results into the deterministic outputs with
`src.decode.merge_outputs` (deterministic non-null fields always win).

This is the sibling of /decode for labels the deterministic layer already
decoded *thinly* (see `enrichment_report.md`). /decode cannot do this: its
step 0 re-runs the deterministic layer, which re-absorbs these labels and
empties the residue.

## Non-negotiable invariants (the cold-start rule)
- **One fresh subagent per label.** Never reuse a subagent across labels; never
  put two labels or any previous output in one context.
- **The subagent sees only the frozen context pack + one label**, exactly as
  produced by `prompt_builder`. The deterministic partial decode is NEVER shown
  to the subagent — enrichment happens at merge time, not in the prompt.
  Corrections live in the KB, never in this prompt.
- **Between runs, only the KB/rules change.** Stamp `kb_version`.

## Inputs
- `residue` — path to `runs/<id>_enrich*/enrichment_residue.jsonl` (rows of
  `{raw_label, source_type}`, written by `python -m src.decode.enrichment`).
- `deterministic` — the outputs.jsonl the selection was made from.

## Procedure
1. **Stamp the context.** `python -m src.decode.context_pack --version` →
   `kb_version`. Count residue rows. Report both to the user before spawning.
2. **Decode each row i (0-based), a few in parallel:**
   1. `python -m src.decode.prompt_builder --input <residue> --index <i>` —
      capture stdout verbatim; that is the entire subagent task.
   2. Spawn a **fresh** subagent (Agent tool, subagent_type `general-purpose`)
      with exactly that prompt. It must return ONLY the JSON object.
   3. Save to `<enrich_dir>/raw/<i>.json`; validate:
      `python -m src.validate.schema_validator --file <enrich_dir>/raw/<i>.json`
   4. **If invalid:** NEW fresh subagent, same prompt plus the validator's
      error lines appended (mirror `build_retry_suffix`). Max 2 retries.
   5. **Still invalid:** keep the object but mark it `"schema_invalid": true`
      (merge_outputs skips it and counts it). Never hand-fix.
3. **Assemble the LLM file.** Write the per-label objects (one per line, with
   `"decode_method": "llm"` and `"decoded_kb_version": "<kb_version>"`) to
   `<enrich_dir>/outputs_llm.jsonl` — a separate file, NEVER appended to the
   deterministic outputs.jsonl (duplicate raw_labels would trip the scorer).
4. **Merge:**
   `python -m src.decode.merge_outputs --deterministic <deterministic>
   --llm <enrich_dir>/outputs_llm.jsonl --out <enrich_dir>/outputs_enriched.jsonl`
   Report the printed stats and, if `merge_conflicts.jsonl` is non-empty, show
   its rows — conflicts are for the human to resolve, never auto-picked.
5. **Point at the next step:** the data cross-check chain
   (`src.profile.cross_check` → `src.profile.relationship_check`) on
   `outputs_enriched.jsonl`, then `python -m src.profile.promote` to nominate
   validated-store candidates.

## Notes
- N labels → N (+retries) subagents, expected; order does not matter.
- The selection already deduped structural families: validating one
  representative and letting sibling inheritance spread it IS the design.
  Run `python -m src.decode.enrichment --full` later only as a mop-up.
