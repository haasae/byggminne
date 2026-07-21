"""Data-profiling layer, step 3 (Phase 2 starter): seasonality + correlation.

Loads a HANDFUL of selected label series fully into memory (unlike series_stats,
which streams everything with O(1) memory) and answers two questions the
per-label statistics cannot:

1. **Seasonal profile** -- monthly mean/min/max per label. An outdoor
   temperature shows the annual sinusoid (winter lows, summer highs); a supply
   air temperature is flat; a heating supply is winter-high/summer-low.
2. **Correlation vs a reference label** -- Pearson r on timestamp-aligned
   samples. CLAUDE.md section 4: heating correlates NEGATIVELY with outdoor
   temperature, cooling POSITIVELY.

Timestamps are matched exactly (string equality) -- valid here because the raw
exports share a fixed grid per building. Months are sliced from the fixed-width
timestamp ('2025-01-01 ...' -> '01'), no datetime parsing.

    python -m src.profile.seasonal_check "data/raw/tasen/*.csv" \
        --labels-file candidates.txt --reference "OU001/FCB.Local Application.-RT401." \
        -o runs/profile/tasen/seasonal_rt401.md

--reference takes a SUBSTRING that must match exactly one loaded label.
"""
import argparse
import math
from pathlib import Path

from src.common.io_utils import configure_stdout_utf8
from src.profile.series_stats import _resolve

MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def load_series(paths, labels):
    """One pass over the files; return {label: {ts: value}} for the given labels."""
    series = {label: {} for label in labels}
    for path in paths:
        with Path(path).open("r", encoding="utf-8-sig", newline="") as fh:
            for line in fh:
                line = line.rstrip("\r\n")
                if not line:
                    continue
                parts = line.rsplit(",", 2)
                if len(parts) != 3:
                    continue
                label = parts[0]
                if label not in series:
                    continue
                try:
                    value = float(parts[2].strip())
                except ValueError:
                    continue
                if math.isnan(value):
                    continue
                series[label][parts[1].strip()] = value  # last wins on duplicate ts
    return series


def monthly_profile(points):
    """{ts: value} -> {month '01'..'12': (mean, n, min, max)}."""
    sums, counts, mins, maxs = {}, {}, {}, {}
    for ts, value in points.items():
        month = ts[5:7]
        sums[month] = sums.get(month, 0.0) + value
        counts[month] = counts.get(month, 0) + 1
        mins[month] = min(mins.get(month, value), value)
        maxs[month] = max(maxs.get(month, value), value)
    return {m: (sums[m] / counts[m], counts[m], mins[m], maxs[m]) for m in sorted(sums)}


def pearson(points_a, points_b):
    """Pearson r over timestamp-aligned samples; returns (r, n_overlap).

    r is None when either aligned series is constant (undefined correlation).
    """
    common = points_a.keys() & points_b.keys()
    n = len(common)
    if n < 2:
        return None, n
    xs = [points_a[ts] for ts in common]
    ys = [points_b[ts] for ts in common]
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sxx = syy = 0.0
    for x, y in zip(xs, ys):
        dx, dy = x - mean_x, y - mean_y
        cov += dx * dy
        sxx += dx * dx
        syy += dy * dy
    if sxx == 0.0 or syy == 0.0:
        return None, n
    return cov / math.sqrt(sxx * syy), n


def resolve_reference(labels, needle):
    """The unique label containing `needle`; raise with candidates otherwise."""
    matches = [label for label in labels if needle in label]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise SystemExit(f"--reference {needle!r} matches no loaded label")
    raise SystemExit(
        f"--reference {needle!r} is ambiguous ({len(matches)} matches):\n  "
        + "\n  ".join(matches)
    )


def _amplitude(profile):
    means = [mean for mean, *_ in profile.values()]
    return (max(means) - min(means)) if means else 0.0


def render_markdown(series, reference=None):
    L = ["# Seasonal profile / correlation check", ""]
    if reference:
        L.append(f"Reference label for correlations: `{reference}`")
        L.append("")

    for label, points in series.items():
        L.append(f"## `{label}`")
        L.append("")
        if not points:
            L.append("_No data found for this label._")
            L.append("")
            continue
        profile = monthly_profile(points)
        L.append(f"- samples: {len(points)}; monthly amplitude "
                 f"(max mean - min mean): **{_amplitude(profile):.1f}**")
        if reference and label != reference:
            r, n = pearson(series[reference], points)
            r_txt = f"{r:+.3f}" if r is not None else "undefined (constant series)"
            L.append(f"- Pearson vs reference: **{r_txt}** (n={n} aligned samples)")
        L.append("")
        L.append("| month | mean | min | max | n |")
        L.append("|---|---|---|---|---|")
        for month, (mean, n, lo, hi) in profile.items():
            name = MONTH_NAMES[int(month) - 1]
            L.append(f"| {name} | {mean:.2f} | {lo:.2f} | {hi:.2f} | {n} |")
        L.append("")
    return "\n".join(L)


def main() -> int:
    configure_stdout_utf8()
    ap = argparse.ArgumentParser(
        description="Monthly profiles for selected labels + Pearson vs a reference label."
    )
    ap.add_argument("inputs", nargs="+", help="CSV files or glob patterns")
    ap.add_argument("--labels-file", required=True,
                    help="text file, one raw_label per line, the series to load")
    ap.add_argument("--reference",
                    help="substring uniquely identifying the reference label for correlations")
    ap.add_argument("-o", "--output", help="write the markdown report here (also printed)")
    args = ap.parse_args()

    labels = [
        line.strip() for line in
        Path(args.labels_file).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    paths = _resolve(args.inputs)
    series = load_series(paths, set(labels))
    # Preserve the labels-file order in the report.
    series = {label: series[label] for label in labels}

    reference = resolve_reference(labels, args.reference) if args.reference else None
    report = render_markdown(series, reference)

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
