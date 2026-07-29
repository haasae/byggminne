"""Phase 2: classify each zone's gain regime from the zone table (no re-stream).

Regimes (knowledge_base/collectief_survey.md): binary on/off (intermediates
are k/n resampling averages), continuous modulating (B01 saturates at 99 --
never threshold on ==100), mixed/uncertain (honest middle), dead, no_data.
All thresholds live in knowledge_base/heating_rules.json.

    python -m src.heating.gain_regime runs/heating/zone_table.jsonl \
        -o runs/heating/regimes.jsonl
"""
import argparse
import json
import sys
from pathlib import Path

from src.common.io_utils import configure_stdout_utf8, read_json, read_jsonl
from src.heating.build_zone_table import DEFAULT_RULES

KN_TOLERANCE = 0.05  # 33.33 in rules vs 33.333333... in data


def _pct_kn(gain, kn_values):
    """Share of samples sitting exactly on k/n resampling averages."""
    top = gain.get("top_values") or []
    n = gain.get("n") or 0
    if not n:
        return 0.0
    hits = sum(
        e["count"] for e in top
        if any(abs(e["value"] - kn) <= KN_TOLERANCE for kn in kn_values)
    )
    return hits / n


def classify(row, rules):
    """zone-table row -> (regime, reasoning). Only meaningful for t_triple."""
    flags = row.get("flags", [])
    stats = row["stats"]
    if "empty" in flags or stats.get("n_data", 0) == 0:
        return "no_data", "file has no data rows"
    if "dead_gain" in flags:
        return "dead", "gain constant at 0 for the whole period"
    gain = stats["gain"]
    if not gain.get("n"):
        return "no_data", "no gain samples"

    pct01 = (gain["pct_at_0"] or 0) + (gain["pct_at_100"] or 0)
    pct_kn = _pct_kn(gain, rules["kn_average_values"])
    binaryish = pct01 + pct_kn
    distinct = gain.get("distinct")  # None == capped == clearly modulating
    interior = gain["pct_interior"] or 0

    if binaryish >= rules["binary_pct_threshold"]:
        return "binary", (
            f"{pct01:.1%} of samples exactly 0/100 (+{pct_kn:.1%} on k/n "
            f"resampling averages) >= {rules['binary_pct_threshold']:.0%}")
    if distinct is None or distinct >= rules["modulating_min_distinct"] \
            or interior >= rules["modulating_min_interior_pct"]:
        d = "capped" if distinct is None else str(distinct)
        return "modulating", (
            f"{interior:.1%} interior samples, {d} distinct values "
            f"(thresholds: >={rules['modulating_min_interior_pct']:.0%} "
            f"interior or >={rules['modulating_min_distinct']} distinct)")
    return "mixed", (
        f"neither binary ({binaryish:.1%} on 0/100/kn) nor modulating "
        f"({interior:.1%} interior, {distinct} distinct) -- honest middle")


def main(argv=None):
    configure_stdout_utf8()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("zone_table")
    ap.add_argument("-o", "--out", default=str(Path("runs") / "heating" / "regimes.jsonl"))
    ap.add_argument("--rules", default=str(DEFAULT_RULES))
    args = ap.parse_args(argv)

    rules = read_json(args.rules)
    counts = {}
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        for row in read_jsonl(args.zone_table):
            if row["kind"] != "t_triple":
                continue
            regime, reasoning = classify(row, rules)
            counts[(row["building"], regime)] = counts.get((row["building"], regime), 0) + 1
            fh.write(json.dumps({
                "building": row["building"],
                "zone": row["zone"],
                "regime": regime,
                "reasoning": reasoning,
                "flags": row.get("flags", []),
            }, ensure_ascii=False) + "\n")

    buildings = sorted({b for b, _ in counts})
    for b in buildings:
        parts = [f"{r}={counts[(b, r)]}" for r in
                 ("binary", "modulating", "mixed", "dead", "no_data")
                 if (b, r) in counts]
        print(f"{b}: " + ", ".join(parts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
