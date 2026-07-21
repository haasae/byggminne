"""Render metrics + error log to report.md, a JSON-serializable dict, and rows
for errors.jsonl (the queue that drives knowledge-base updates).
"""
from src.score.field_compare import CORRECT


def _pct(x):
    return "n/a" if x is None else f"{100 * x:.1f}%"


def _round(x, n=3):
    return None if x is None else round(x, n)


def build_error_rows(metrics, schema_invalid=None):
    """One row per field miss, plus one row per schema-invalid output."""
    errors = []
    for row in metrics["rows"]:
        for r in row["results"]:
            if r.verdict == CORRECT:
                continue
            errors.append({
                "raw_label": row["raw_label"],
                "field": r.path,
                "kind": r.verdict,
                "predicted": r.predicted,
                "gold": r.gold,
                "confidence": row["confidence"],
            })
    for raw_label, messages in (schema_invalid or {}).items():
        errors.append({
            "raw_label": raw_label,
            "field": "(schema)",
            "kind": "SCHEMA_INVALID",
            "predicted": "; ".join(f"{loc}: {msg}" for loc, msg in messages),
            "gold": None,
            "confidence": None,
        })
    return errors


def _calibration_json(cal):
    return {
        "n": cal["n"],
        "skipped_no_confidence": cal["skipped_no_confidence"],
        "brier": _round(cal["brier"]),
        "ece": _round(cal["ece"]),
        "bins": [
            {
                "range": f"[{b['lo']:.1f},{b['hi']:.1f}]",
                "n": b["n"],
                "accuracy": _round(b["accuracy"]),
                "mean_confidence": _round(b["mean_confidence"]),
                "wilson": [_round(b["wilson"][0]), _round(b["wilson"][1])] if b["wilson"] else None,
            }
            for b in cal["bins"]
        ],
    }


def metrics_to_json(metrics):
    """Convert the metrics dict (with dataclasses inside) to plain JSON types."""
    field_stats = {}
    for path, st in metrics["field_stats"].items():
        field_stats[path] = {
            "tier": st.tier,
            "overall_acc": _round(st.overall_acc),
            "overall_total": st.overall_total,
            "nontrivial_acc": _round(st.nontrivial_acc),
            "nontrivial_total": st.nontrivial_total,
            "under_fill": st.under_fill,
            "over_fill": st.over_fill,
            "wrong_value": st.wrong_value,
            "exact_acc": _round(st.exact_acc),
            "exact_total": st.exact_total,
        }
    return {
        "n_matched": metrics["n_matched"],
        "n_outputs": metrics.get("n_outputs"),
        "schema_validity_rate": _round(metrics.get("schema_validity_rate")),
        "exact_match_rate": _round(metrics["exact_match_rate"]),
        "core_exact_rate": _round(metrics["core_exact_rate"]),
        "field_stats": field_stats,
        "calibration": _calibration_json(metrics["calibration"]),
        "integrity": metrics.get("integrity"),
    }


def render_markdown(metrics, alignment=None):
    L = ["# Decode evaluation report", ""]
    L.append(f"- Matched rows: **{metrics['n_matched']}**")
    if metrics.get("n_outputs") is not None:
        L.append(f"- Outputs scored: {metrics['n_outputs']}")
    if "schema_validity_rate" in metrics:
        L.append(f"- Schema-validity rate: **{_pct(metrics['schema_validity_rate'])}**")
    L.append(f"- Exact-match rate (all scored fields): **{_pct(metrics['exact_match_rate'])}**")
    L.append(f"- Core-exact rate (CORE fields): **{_pct(metrics['core_exact_rate'])}**")
    L.append("")

    L.append("## Per-field accuracy")
    L.append("")
    L.append("| field | tier | overall | non-null | under | over | wrong | code-exact |")
    L.append("|---|---|---|---|---|---|---|---|")
    for path, st in metrics["field_stats"].items():
        code_exact = _pct(st.exact_acc) if st.exact_total else "-"
        L.append(
            f"| {path} | {st.tier} | {_pct(st.overall_acc)} ({st.overall_total}) | "
            f"{_pct(st.nontrivial_acc)} ({st.nontrivial_total}) | {st.under_fill} | "
            f"{st.over_fill} | {st.wrong_value} | {code_exact} |"
        )
    L.append("")

    cal = metrics["calibration"]
    L.append("## Confidence calibration")
    L.append("")
    L.append(f"- Points: {cal['n']} (skipped, no confidence: {cal['skipped_no_confidence']})")
    L.append(f"- Brier score: {_round(cal['brier'])} . ECE: {_round(cal['ece'])}")
    if cal["n"] < 50:
        L.append("- _Small N: calibration here is indicative, not conclusive._")
    L.append("")
    L.append("| conf range | n | accuracy | mean conf | 95% CI |")
    L.append("|---|---|---|---|---|")
    for b in cal["bins"]:
        ci = f"[{_pct(b['wilson'][0])}, {_pct(b['wilson'][1])}]" if b["wilson"] else "-"
        L.append(
            f"| [{b['lo']:.1f},{b['hi']:.1f}] | {b['n']} | {_pct(b['accuracy'])} | "
            f"{_round(b['mean_confidence'])} | {ci} |"
        )
    L.append("")

    integ = metrics.get("integrity")
    if integ:
        L.append("## Integrity")
        L.append("")
        L.append(f"- Gold labels missing from outputs: {len(integ.get('missing_in_outputs', []))}")
        L.append(f"- Extra outputs not in gold: {len(integ.get('extra_in_outputs', []))}")
        L.append(f"- Duplicate output keys: {len(integ.get('duplicate_output_keys', []))}")
        if integ.get("near_miss_keys"):
            L.append(f"- **Near-miss keys (decoder altered raw_label): {len(integ['near_miss_keys'])}**")
        L.append("")

    return "\n".join(L)
