# AGENTS.md — orientation for non-Claude coding agents (Codex, etc.)

This project's agent instructions live in **`CLAUDE.md`** (project map,
architecture, label grammar, working rules). Read it first — everything in it
applies to you too; only the filename is Claude-specific.

## The LLM procedures

The LLM leg of the pipeline is written as Claude Code "skills", but they are
plain-markdown procedures any agent can follow:

- `.claude/skills/decode/SKILL.md` — decode the labels the deterministic
  layer could not resolve (`residue.jsonl`).
- `.claude/skills/enrich/SKILL.md` — enrich thin-but-valid decodes.

**Non-negotiable when following either procedure:** each label is decoded by
ONE fresh, isolated model context that sees only the frozen context pack plus
that single label — never a shared conversation and never another label's
answer (the cold-start rule, `docs/EVALUATION.md`). If you cannot spawn
isolated per-label contexts, do not improvise: fall back to the copy-paste
harness (`python -m src.decode.manual_batch export` / `collect` — see
`docs/BRUKERVEILEDNING_PIPELINE.md` ch. 7), which enforces the same contract
with a human doing the pasting.

## House rules that bite

- ASCII-only file/directory/identifier names; æ/ø/å only inside UTF-8 file
  *content*. Read and write everything as UTF-8 (labels are Norwegian).
- Never commit building data: `data/raw/`, `data/training/`,
  `knowledge_base/incoming/`, building surveys and `knowledge_base/school_index/`
  are local-only (see `.gitignore`).
- Never invent a meaning for an unknown code — leave the field `null` with low
  confidence. Partial decoding is valid output.
- The system learns by accumulating files in `knowledge_base/`, never through
  prompt memory.
- Run `python -m pytest -q` before claiming work done.
