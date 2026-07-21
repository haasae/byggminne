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
- Stored as JSON conforming to the schema: batches live in
  `data/eval/batches/<id>/input.jsonl`, gold in `tests/gold/<id>/gold.jsonl`.

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

## How to run it (commands)

All commands run from the repo root, inside the venv, with `PYTHONIOENCODING=utf-8`.
None of them spend LLM tokens except the `/decode` skill step.

**0. Sanity: the automated suite.** Includes an end-to-end harness test
(batch → decode → score → summary) on hermetic fixtures:

```bash
python -m pytest -q
```

**1. Try a single label** — the quickest manual test. Prints the structured
output, how it was decoded, confidence, and whether the batch pipeline would
send it to the LLM layer:

```bash
python -m src.decode.try_label "PS4001:472-OU001/-RT401.#1" --source-type bacnet
```

**2. Evaluate a whole batch** — one command: deterministic decode → score vs
gold (if `tests/gold/<id>/gold.jsonl` exists) → human-readable showcase →
`summary.md` with the headline numbers:

```bash
python -m src.eval.run_eval --batch b001          # has gold -> full metrics
python -m src.eval.run_eval --batch b_all_tasen   # no gold -> coverage + showcase
```

Results land in `runs/<id>_eval_<kb_version>/`: `summary.md` (start here),
`coverage.md`, `showcase.md`, and with gold also `report.md` / `report.json` /
`errors.jsonl` (the miss queue that drives KB updates).

**3. The LLM leg (residue).** `summary.md` reports how many labels the
deterministic layer could not decode. Run the `/decode` skill on that batch
(fresh subagent per residue label, appended to `runs/<id>/outputs.jsonl`),
then re-score the merged file:

```bash
python -m src.eval.run_eval --batch <id> --outputs runs/<id>/outputs.jsonl
```

**Individual pieces** (what run_eval chains for you):

```bash
python -m src.extract.unique_labels data/raw/<file>.csv -o labels.txt
python -m src.extract.build_batch labels.txt --source-type bacnet -o data/eval/batches/<id>/input.jsonl
python -m src.decode.deterministic_batch --input data/eval/batches/<id>/input.jsonl --out-dir runs/<id>_det
python -m src.score.run_score --outputs runs/<id>/outputs.jsonl --gold tests/gold/<id>/gold.jsonl --out-dir runs/<id>
```

**Reading the numbers honestly.** Every summary reports the validated-store
overlap (exact / sibling / unseen). An *exact* store hit replays a decode a
human already validated, so accuracy on those labels measures **KB recall,
not generalization** — `b001` scores 100% *by construction* because the store
was seeded from its gold. To measure generalization, score a batch whose
labels are *unseen* by the store. Growing gold for unseen labels is the main
manual task; prefer confirming decodes via the §4 data cross-checks
(`src/profile/`) over hand-labeling from intuition.

## Open questions to confirm
- Batch size, number of batches, gold-set size.
- Which fields are "must-be-exact" vs "nice-to-have" for scoring weight.
