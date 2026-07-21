"""Aggregate per-field results into the headline metrics + confidence calibration.

Headlines (docs/EVALUATION.md):
- schema-validity rate, exact-match rate (all scored fields), core-exact rate.
- per-field accuracy reported twice: overall, and "non-trivial" (gold non-null)
  so a mostly-null field cannot inflate the headline.
- calibration as reliability bins + Brier + ECE, honest about small N.
"""
import math
from dataclasses import dataclass

from src.common.fields import CODE, core_fields, scored_fields
from src.score.field_compare import (
    OVER_FILL,
    UNDER_FILL,
    WRONG_VALUE,
    compare_row,
)


def _wilson(p, n, z=1.96):
    """Wilson 95% interval for a proportion -- honest error bars at small N."""
    if n == 0:
        return (0.0, 0.0)
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


@dataclass
class FieldStat:
    path: str
    tier: str
    overall_correct: int = 0
    overall_total: int = 0
    nontrivial_correct: int = 0
    nontrivial_total: int = 0
    under_fill: int = 0
    over_fill: int = 0
    wrong_value: int = 0
    exact_correct: int = 0   # CODE only
    exact_total: int = 0     # CODE only

    @property
    def overall_acc(self):
        return self.overall_correct / self.overall_total if self.overall_total else None

    @property
    def nontrivial_acc(self):
        return self.nontrivial_correct / self.nontrivial_total if self.nontrivial_total else None

    @property
    def exact_acc(self):
        return self.exact_correct / self.exact_total if self.exact_total else None


def _calibration(rows, n_bins=5):
    pts = [
        (r["confidence"], 1 if r["exact_match"] else 0)
        for r in rows
        if isinstance(r["confidence"], (int, float))
    ]
    n = len(pts)
    edges = [i / n_bins for i in range(n_bins + 1)]
    bins = []
    for b in range(n_bins):
        lo, hi = edges[b], edges[b + 1]
        if b == n_bins - 1:   # last bin is closed on the right so confidence==1.0 lands somewhere
            members = [(c, y) for (c, y) in pts if lo <= c <= hi]
        else:
            members = [(c, y) for (c, y) in pts if lo <= c < hi]
        bn = len(members)
        acc = sum(y for _, y in members) / bn if bn else None
        mean_conf = sum(c for c, _ in members) / bn if bn else None
        bins.append({
            "lo": lo,
            "hi": hi,
            "n": bn,
            "accuracy": acc,
            "mean_confidence": mean_conf,
            "wilson": _wilson(acc, bn) if bn else None,
        })
    brier = sum((c - y) ** 2 for c, y in pts) / n if n else None
    ece = sum((b["n"] / n) * abs(b["accuracy"] - b["mean_confidence"]) for b in bins if b["n"]) if n else None
    return {
        "n": n,
        "skipped_no_confidence": len(rows) - n,
        "bins": bins,
        "brier": brier,
        "ece": ece,
    }


def compute_metrics(matched, schema_valid_map=None, n_outputs=None):
    specs = scored_fields()
    core = {f.path for f in core_fields()}
    stats = {f.path: FieldStat(f.path, f.tier) for f in specs}

    rows = []
    exact_match_count = 0
    core_exact_count = 0

    for raw_label, pred, gold in matched:
        results = compare_row(pred, gold, specs)
        row_exact = True
        row_core_exact = True
        for r in results:
            st = stats[r.path]
            st.overall_total += 1
            if r.correct:
                st.overall_correct += 1
            if r.gold_nonnull:
                st.nontrivial_total += 1
                if r.correct:
                    st.nontrivial_correct += 1
            if r.verdict == UNDER_FILL:
                st.under_fill += 1
            elif r.verdict == OVER_FILL:
                st.over_fill += 1
            elif r.verdict == WRONG_VALUE:
                st.wrong_value += 1
            if r.kind == CODE and r.exact is not None:
                st.exact_total += 1
                if r.exact:
                    st.exact_correct += 1
            if not r.correct:
                row_exact = False
                if r.path in core:
                    row_core_exact = False
        exact_match_count += int(row_exact)
        core_exact_count += int(row_core_exact)
        rows.append({
            "raw_label": raw_label,
            "results": results,
            "exact_match": row_exact,
            "core_exact": row_core_exact,
            "confidence": pred.get("confidence"),
        })

    n_matched = len(matched)
    metrics = {
        "n_matched": n_matched,
        "n_outputs": n_outputs,
        "exact_match_rate": exact_match_count / n_matched if n_matched else None,
        "core_exact_rate": core_exact_count / n_matched if n_matched else None,
        "field_stats": stats,
        "rows": rows,
        "calibration": _calibration(rows),
    }
    if schema_valid_map is not None and n_outputs:
        valid = sum(1 for v in schema_valid_map.values() if v)
        metrics["schema_valid_count"] = valid
        metrics["schema_validity_rate"] = valid / n_outputs
    return metrics
