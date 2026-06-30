# label-decoder — Evaluation & Testing Protocol

*Companion to CLAUDE.md. CLAUDE.md owns the architecture and decode rules; this doc
owns **how we measure decoding quality**. This is the current round's deliverable.*

> Permanent project facts (system codes, TFM grammar, undernummer semantics, the
> AV-as-binary trap, encoding rules, Brick-as-future-goal) live in **CLAUDE.md** —
> that is the single source of truth. Do not duplicate them here.

---

## Why this doc exists
CLAUDE.md §2 states the core principle: the system improves by **accumulating in the
knowledge base, NOT by the LLM "learning" from prompts.** This document turns that
principle into a *test*: prove that a cold-start session — or a different LLM — given
only `(rules + current KB + a batch of labels)`, decodes as well as the local setup.

## Two kinds of checking (do not conflate)
1. **Data cross-check — in-decoder confidence** (CLAUDE.md §4). Uses the measurement
   values to test whether a name-based guess is physically plausible (heating
   correlates negatively with outdoor temp, binary ⇒ exactly 2 values, cumulative
   energy is monotonic, etc.). This raises or lowers confidence on a *single* decode.
2. **Evaluation harness — this doc.** Measures decoding *accuracy*, per batch, against
   a human-validated gold set. Answers "how well is the whole system doing, and is it
   improving?"

They are complementary: cross-checks make each decode better; the harness measures the
system. Where possible, a gold decoding should itself survive the §4 cross-checks.

## The cold-start rule (non-negotiable)
- The decoder is a **stateless function**: script → **single fresh LLM call** → JSON
  validated against `schema/decoded_label.schema.json`. No interactive chat; no
  conversation history carried between labels or batches.
- Between runs, the **only** thing that may change is the **KB / context files.**
- When the LLM is wrong, the fix goes into the **KB or the rules** — never into a
  growing prompt of worked examples — and a **fresh** run confirms it generalizes.
- Corollary: keep the *LLM under test* (a script's API call) separate from the Claude
  Code session used to *build* the harness. That separation is what makes
  "no in-session learning" automatic.

## Gold set
- Me, a human expert provides correct decodings for an evaluation set — "as well as
  I can locally" is the benchmark.
- Stored as JSON conforming to the schema, kept alongside its batch (e.g.
  `data/training/` or a `tests/gold/` tree).

## What to measure, per batch
- **Schema-validity rate** — fraction of outputs that validate.
- **Exact-match rate** — all fields correct vs gold.
- **Per-field accuracy** — `system_code`, `number`, `undernummer`, `component`,
  `measurement_type`, `location`, … (the diagnostic metric — tells you *where* it fails).
- **Confidence calibration** — accuracy vs the decoder's stated confidence (CLAUDE.md
  §5 requires a calibrated `confidence`).
- **Error log** — per miss: field + predicted vs gold. This is the queue that drives KB
  updates.

## The loop
Run batch (cold) → score → log misses → update KB / rules (not prompt examples) →
re-run a **fresh** batch → confirm the metric moved. Repeat.

## Open questions to confirm
- Batch size, number of batches, gold-set size.
- Which fields are "must-be-exact" vs "nice-to-have" for scoring weight.
- Where gold + batches live (`data/training/` vs a dedicated `tests/` tree).
