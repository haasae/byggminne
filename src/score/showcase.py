"""Render decoder outputs into a human-friendly showcase report (no gold needed).

Unlike run_score (which measures accuracy against gold), the showcase presents
WHAT the decoder produced so a person can judge it at a glance: schema validity,
confidence distribution, how often each field was resolved, and a per-label
table with the decoded meaning and the decoder's own reasoning.

    python -m src.score.showcase --outputs runs/<id>/outputs.jsonl \
        [--run-meta runs/<id>/run_meta.json] -o runs/<id>/showcase.md
"""
import argparse
from pathlib import Path

from src.common.fields import get_value
from src.common.io_utils import configure_stdout_utf8, read_json, read_jsonl
from src.validate.schema_validator import build_validator, validate_instance

# Fields shown in the summary fill-rate table and the per-label details.
DISPLAY_FIELDS = (
    ("primary_system.code", "system code"),
    ("primary_system.description", "system meaning"),
    ("component", "component"),
    ("measurement_type", "measured quantity"),
    ("function", "function"),
    ("carrier", "carrier"),
    ("object_type", "BACnet type"),
    ("location.building", "building"),
    ("location.zone", "zone"),
    ("unit", "unit"),
)


def _bar(fraction, width=20):
    """ASCII bar, e.g. '##########----------' for 0.5."""
    filled = round(fraction * width)
    return "#" * filled + "-" * (width - filled)


def _fmt(value):
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _short(label, max_len=60):
    """Show the tail of a long label -- the discriminating part."""
    return label if len(label) <= max_len else "…" + label[-(max_len - 1):]


def render_showcase(outputs, run_meta=None, schema_path=None):
    validator = build_validator(schema_path)
    n = len(outputs)
    valid_flags = [not validate_instance(row, validator) for row in outputs]
    n_valid = sum(valid_flags)
    confidences = [
        row.get("confidence") for row in outputs
        if isinstance(row.get("confidence"), (int, float))
    ]

    L = ["# Label decode showcase", ""]
    if run_meta:
        L.append(
            f"Run: `{run_meta.get('input', '?')}` · model `{run_meta.get('model', '?')}` "
            f"· KB version `{run_meta.get('kb_version', '?')}`"
        )
        L.append("")

    # --- Headline numbers -------------------------------------------------
    L.append("## At a glance")
    L.append("")
    L.append(f"- Labels decoded: **{n}**")
    L.append(f"- Structurally valid outputs (schema): **{n_valid}/{n}**"
             + (f" (**{100 * n_valid / n:.0f}%**)" if n else ""))
    if confidences:
        mean_c = sum(confidences) / len(confidences)
        L.append(f"- Mean self-reported confidence: **{mean_c:.2f}**")
    L.append("")

    if confidences:
        L.append("### Confidence distribution")
        L.append("")
        L.append("```")
        for lo in (0.0, 0.2, 0.4, 0.6, 0.8):
            hi = lo + 0.2
            members = [c for c in confidences
                       if (lo <= c < hi) or (hi == 1.0 and c == 1.0)]
            frac = len(members) / len(confidences)
            L.append(f"{lo:.1f}-{hi:.1f}  {_bar(frac)}  {len(members)}")
        L.append("```")
        L.append("")

    # --- Field fill-rates --------------------------------------------------
    L.append("### How often each field was resolved")
    L.append("")
    L.append("| field | resolved | of labels |")
    L.append("|---|---|---|")
    for path, title in DISPLAY_FIELDS:
        filled = sum(1 for row in outputs if get_value(row, path) is not None)
        frac = filled / n if n else 0.0
        L.append(f"| {title} | `{_bar(frac)}` {100 * frac:.0f}% | {filled}/{n} |")
    L.append("")
    L.append("_A blank field is not an error: the decoder must leave a field"
             " null rather than guess (partial decoding is valid)._")
    L.append("")

    # --- Overview table ----------------------------------------------------
    L.append("## Decoded labels (overview)")
    L.append("")
    L.append("| # | label (tail) | system | component | measures | function | conf |")
    L.append("|---|---|---|---|---|---|---|")
    for i, row in enumerate(outputs):
        system = get_value(row, "primary_system.code")
        desc = get_value(row, "primary_system.description")
        sys_txt = _fmt(system) + (f" ({desc})" if system and desc else "")
        conf = row.get("confidence")
        conf_txt = f"{conf:.2f}" if isinstance(conf, (int, float)) else "—"
        flag = "" if valid_flags[i] else " ⚠invalid"
        L.append(
            f"| {i} | `{_short(row.get('raw_label', '?'))}`{flag} | {sys_txt} | "
            f"{_fmt(get_value(row, 'component'))} | "
            f"{_fmt(get_value(row, 'measurement_type'))} | "
            f"{_fmt(get_value(row, 'function'))} | {conf_txt} |"
        )
    L.append("")

    # --- Per-label details ---------------------------------------------------
    L.append("## Per-label details")
    L.append("")
    for i, row in enumerate(outputs):
        L.append(f"### {i}. `{row.get('raw_label', '?')}`")
        L.append("")
        if not valid_flags[i]:
            L.append("**⚠ Output did not conform to the schema** — counted against validity.")
            L.append("")
            continue
        for path, title in DISPLAY_FIELDS:
            value = get_value(row, path)
            if value is not None:
                L.append(f"- **{title}:** {_fmt(value)}")
        conf = row.get("confidence")
        if isinstance(conf, (int, float)):
            L.append(f"- **confidence:** `{_bar(conf)}` {conf:.2f}")
        if row.get("reasoning"):
            L.append(f"- **decoder's reasoning:** {row['reasoning']}")
        L.append("")

    return "\n".join(L)


def main() -> int:
    configure_stdout_utf8()
    ap = argparse.ArgumentParser(description="Render outputs.jsonl into showcase.md (no gold needed).")
    ap.add_argument("--outputs", required=True)
    ap.add_argument("--run-meta", help="optional run_meta.json for the header")
    ap.add_argument("-o", "--output", required=True, help="showcase markdown path")
    ap.add_argument("--schema", help="schema path (defaults to schema/decoded_label.schema.json)")
    args = ap.parse_args()

    outputs = read_jsonl(args.outputs)
    run_meta = read_json(args.run_meta) if args.run_meta else None
    text = render_showcase(outputs, run_meta=run_meta, schema_path=args.schema)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"showcase -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
