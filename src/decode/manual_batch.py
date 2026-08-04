"""Copy-paste LLM harness: decode residue labels with ANY chat LLM.

For users without Claude Code (or any agentic tool): `export` writes one
self-contained prompt file per residue label; the user pastes each into a
FRESH chat (one label per chat -- the cold-start rule) and saves the reply;
`collect` validates every reply, writes a fresh retry prompt for each reject,
and assembles the accepted rows.

    python -m src.decode.manual_batch export --input runs/<id>/residue.jsonl \\
        --out-dir runs/<id>_manual
    # ... paste prompts/NNN.txt into a fresh chat, save reply as replies/NNN.txt ...
    python -m src.decode.manual_batch collect --dir runs/<id>_manual \\
        [--deterministic runs/<id>/outputs.jsonl] [--out runs/<id>/outputs_full.jsonl]

Accepted rows land in <dir>/outputs_llm.jsonl (stamped decode_method=llm),
ready for src.decode.merge_outputs (enrichment mode) or, with --deterministic,
concatenated into a complete outputs file (residue mode).
"""
import argparse
import json
from pathlib import Path

from src.common.io_utils import (
    configure_stdout_utf8,
    read_json,
    read_jsonl,
    write_json,
    write_jsonl,
)
from src.decode.context_pack import build_context_pack
from src.decode.decode_label import extract_json
from src.decode.prompt_builder import build_prompt, build_retry_suffix
from src.validate.schema_validator import build_validator, validate_instance

INSTRUCTIONS_TXT = """\
How to decode these labels with any chat LLM (ChatGPT, Gemini, claude.ai, ...)

1. Open prompts/000.txt and copy ALL of it.
2. Paste it into a brand-NEW chat and send. One label per chat, always --
   never reuse a chat for the next label (answers would contaminate each other).
3. Save the model's whole reply as replies/000.txt (same number as the prompt).
   Code fences or extra prose around the JSON are fine.
4. Repeat for every file in prompts/.
5. Run:  python -m src.decode.manual_batch collect --dir <this folder>
   It writes outputs_llm.jsonl and, for every rejected reply, a corrected
   prompt in retry/. Paste each retry prompt into a NEW chat, overwrite the
   reply file, and run collect again.
"""


def _name(index):
    return f"{index:03d}"


def run_export(input_path, out_dir):
    rows = read_jsonl(input_path)
    context, kb_version = build_context_pack()
    out = Path(out_dir)
    (out / "prompts").mkdir(parents=True, exist_ok=True)
    (out / "replies").mkdir(parents=True, exist_ok=True)
    manifest = []
    for i, row in enumerate(rows):
        prompt = build_prompt(row["raw_label"], row["source_type"], context)
        (out / "prompts" / f"{_name(i)}.txt").write_text(prompt, encoding="utf-8")
        manifest.append(
            {"index": i, "raw_label": row["raw_label"], "source_type": row["source_type"]}
        )
    write_jsonl(out / "manifest.jsonl", manifest)
    write_json(
        out / "meta.json", {"kb_version": kb_version, "input": str(input_path), "n": len(rows)}
    )
    (out / "INSTRUCTIONS.txt").write_text(INSTRUCTIONS_TXT, encoding="utf-8")
    print(f"{len(rows)} prompts -> {out / 'prompts'}")
    print(f"paste each into a FRESH chat; save each reply as {out / 'replies' / 'NNN.txt'}")
    print(f"then: python -m src.decode.manual_batch collect --dir {out}")
    return 0


def _read_reply(replies_dir, name):
    for ext in (".txt", ".json"):
        path = replies_dir / f"{name}{ext}"
        if path.exists():
            # utf-8-sig: Notepad "Save as UTF-8" on Windows may prepend a BOM
            return path.read_text(encoding="utf-8-sig")
    return None


def run_collect(dir_path, deterministic=None, out=None, schema=None):
    d = Path(dir_path)
    manifest = read_jsonl(d / "manifest.jsonl")
    meta = read_json(d / "meta.json")
    validator = build_validator(schema)
    retry_dir = d / "retry"

    context = None  # built lazily -- only needed when a retry prompt must be written

    def write_retry(row, errors):
        nonlocal context
        if context is None:
            context, kb_version = build_context_pack()
            if kb_version != meta.get("kb_version"):
                print(
                    f"WARNING: knowledge base changed since export "
                    f"({meta.get('kb_version')} -> {kb_version}); consider re-running export"
                )
        retry_dir.mkdir(exist_ok=True)
        text = build_prompt(row["raw_label"], row["source_type"], context) + build_retry_suffix(errors)
        (retry_dir / f"{_name(row['index'])}.txt").write_text(text, encoding="utf-8")

    accepted, missing, rejected = [], [], []
    for row in manifest:
        name = _name(row["index"])
        text = _read_reply(d / "replies", name)
        if text is None:
            missing.append(name)
            continue
        try:
            instance = extract_json(text)
        except (ValueError, json.JSONDecodeError):
            write_retry(row, [("(parse)", "output was not a single valid JSON object")])
            rejected.append(name)
            continue
        errors = validate_instance(instance, validator)
        if not errors and instance.get("raw_label") != row["raw_label"]:
            errors = [("raw_label", f"must echo the label verbatim: {row['raw_label']}")]
        if errors:
            write_retry(row, errors)
            rejected.append(name)
            continue
        instance["decode_method"] = "llm"
        instance["decoded_kb_version"] = meta.get("kb_version")
        accepted.append(instance)

    write_jsonl(d / "outputs_llm.jsonl", accepted)
    print(f"accepted {len(accepted)}/{len(manifest)} replies -> {d / 'outputs_llm.jsonl'}")
    if missing:
        print(f"missing {len(missing)} replies: {', '.join(missing)}")
    if rejected:
        print(
            f"rejected {len(rejected)} -> fresh retry prompts in {retry_dir} "
            "(paste into a NEW chat, overwrite the reply file, re-run collect)"
        )

    if deterministic:
        det = read_jsonl(deterministic)
        seen = {r.get("raw_label") for r in det}
        dupes = [r["raw_label"] for r in accepted if r["raw_label"] in seen]
        if dupes:
            print(f"skipping {len(dupes)} llm rows already decoded deterministically")
        combined = det + [r for r in accepted if r["raw_label"] not in seen]
        out_path = Path(out) if out else d / "outputs_full.jsonl"
        write_jsonl(out_path, combined)
        print(f"combined {len(combined)} rows -> {out_path}")
    return 0


def main() -> int:
    configure_stdout_utf8()
    ap = argparse.ArgumentParser(
        description="Copy-paste harness: decode residue labels with any chat LLM."
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("export", help="write one self-contained prompt file per label")
    ex.add_argument("--input", required=True, help="residue.jsonl (or enrichment_residue.jsonl)")
    ex.add_argument("--out-dir", required=True)
    co = sub.add_parser("collect", help="validate the pasted replies, assemble outputs")
    co.add_argument("--dir", required=True, help="the export --out-dir")
    co.add_argument(
        "--deterministic",
        help="deterministic outputs.jsonl to concatenate with (residue mode)",
    )
    co.add_argument("--out", help="combined output path (default: <dir>/outputs_full.jsonl)")
    co.add_argument("--schema", help="schema path override (mainly for tests)")
    args = ap.parse_args()
    if args.cmd == "export":
        return run_export(args.input, args.out_dir)
    return run_collect(args.dir, args.deterministic, args.out, args.schema)


if __name__ == "__main__":
    raise SystemExit(main())
