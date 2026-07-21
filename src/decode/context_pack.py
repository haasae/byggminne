"""Assemble the FROZEN, example-free context pack the decoder sees.

The pack = decode rules + the knowledge-base markdown + the output schema. It is
identical for every label in a run; between runs the ONLY thing that may change
is the KB / rules. We stamp a content hash (kb_version) so that when a metric
moves, the change is attributable to a specific KB state.
"""
import argparse
import hashlib
from pathlib import Path

from src.common.io_utils import configure_stdout_utf8, default_schema_path, repo_root

# KB files included verbatim, each behind a citable SOURCE header. Order is
# fixed so the kb_version hash is stable.
KB_FILES = (
    "knowledge_base/decode_rules.md",
    "knowledge_base/bacnet_sd_label_grammar.md",
    "knowledge_base/control_number_area_map.md",
    "knowledge_base/data_observations.md",
    "knowledge_base/TFM_systemkodeliste_dir/TFM_systemkodeliste.md",
    "knowledge_base/komponentkodeliste_dir/komponentkodeliste.md",
)

# Copyrighted standards (Standard Norge) excluded from the public repo; users
# supply their own converted copies (see README). Missing -> explicit stub
# section, so the pack never shrinks silently and kb_version stays attributable.
OPTIONAL_KB_FILES = (
    "knowledge_base/NS-3451_dir/NS-3451.md",
    "knowledge_base/NS-3457_dir/NS-3457.md",
)


def build_context_pack(root=None, schema_path=None):
    """Return (context_text, kb_version).

    A missing required KB file is FATAL: silently shrinking the pack would
    change kb_version without saying why, and every decode would quietly lose
    a source -- the exact attribution failure the hash exists to prevent.
    Optional (user-supplied) files degrade to a stub section instead.
    """
    root = Path(root) if root else repo_root()
    missing = [rel for rel in KB_FILES if not (root / rel).exists()]
    if missing:
        raise FileNotFoundError(
            "context pack is missing KB file(s): "
            + ", ".join(missing)
            + f" (looked under {root}). If a file was renamed, update KB_FILES "
            "in src/decode/context_pack.py."
        )
    parts = []
    for rel in KB_FILES:
        p = root / rel
        parts.append(f"\n===== SOURCE: {rel} =====\n")
        parts.append(p.read_text(encoding="utf-8"))
    for rel in OPTIONAL_KB_FILES:
        p = root / rel
        if p.exists():
            parts.append(f"\n===== SOURCE: {rel} =====\n")
            parts.append(p.read_text(encoding="utf-8"))
        else:
            parts.append(f"\n===== SOURCE: {rel} (NOT AVAILABLE) =====\n")
            parts.append(
                "This user-supplied reference (copyrighted standard) is not "
                "present; decodes cannot cite it. See README.\n"
            )

    schema_text = Path(schema_path or default_schema_path()).read_text(encoding="utf-8")
    parts.append("\n===== OUTPUT SCHEMA (schema/decoded_label.schema.json) =====\n")
    parts.append(schema_text)

    context = "".join(parts)
    version = hashlib.sha256(context.encode("utf-8")).hexdigest()[:12]
    return context, version


def main() -> int:
    configure_stdout_utf8()
    ap = argparse.ArgumentParser(description="Print the decode context pack or its version hash.")
    ap.add_argument("--version", action="store_true", help="print only the kb_version hash")
    args = ap.parse_args()
    context, version = build_context_pack()
    print(version if args.version else context)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
