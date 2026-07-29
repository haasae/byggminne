"""Phase 3: per-zone heating-type hypothesis (the flexibility-critical field).

COLLECTiEF's ontologies type every actuator as boilerplate Valve_Position_
Command -- so this verdict is inferred from DATA: gain regime (Phase 2) +
thermal response (step_response) + building metadata prior. Output follows
the project's output contract (CLAUDE.md section 5): verdict, calibrated
confidence, reasoning string; ambiguous is an honest answer.

    python -m src.heating.heating_type runs/heating/regimes.jsonl \
        runs/heating/step_summary.jsonl -o runs/heating/heating_types.jsonl
"""
import argparse
import json
import sys
from pathlib import Path

from src.common.io_utils import configure_stdout_utf8, read_json, read_jsonl
from src.heating.build_zone_table import DEFAULT_RULES

# Building priors from metadata (knowledge_base/collectief_survey.md, building
# profiles table). A prior ADJUSTS confidence; it never overrides the data.
PRIORS = {
    "B01": "hydronic",   # W2W HP + el. boiler + radiators
    "B02": "hydronic",   # hydronic radiators + radiant floors
    "B03": "ambiguous",  # "el. boiler + decentralized radiators" -- unclear
    "B04": "mixed",      # A2W HP + radiant floors + fan-coils
    "B05": "electric",   # no plant modeled; likely electric
    "B06": "hydronic",   # district heating
    "B07": "electric",   # decentralized radiators only; likely electric
}


def classify(regime_row, step_row, ht_rules):
    """-> dict(verdict, confidence, reasoning). Data first, prior second."""
    regime = regime_row["regime"]
    building = regime_row["building"]
    prior = PRIORS.get(building)
    if regime in ("dead", "no_data"):
        return {"verdict": "excluded", "confidence": 1.0,
                "reasoning": f"regime={regime}; no live heating signal"}

    n_events = step_row["n_events"] if step_row else 0
    m1k = (step_row or {}).get("minutes_to_1k") or None
    no_drop = (step_row or {}).get("no_1k_drop_share")
    if n_events < ht_rules["min_events"] or (m1k is None and no_drop in (None, 0)):
        return {"verdict": "ambiguous", "confidence": 0.3,
                "reasoning": f"only {n_events} usable setback events "
                             f"(<{ht_rules['min_events']}); regime={regime}, "
                             f"prior={prior} -- insufficient thermal evidence"}

    median = m1k["median"] if m1k else None
    fast = median is not None and median <= ht_rules["fast_max_min_to_1k"]
    slow = median is not None and median >= ht_rules["slow_min_min_to_1k"]
    barely_drops = (no_drop or 0) >= ht_rules["floor_no_drop_share"]

    if fast and regime == "binary":
        conf = 0.8
        note = ""
        if prior == "electric":
            conf = 0.9
        elif prior in ("hydronic",):
            conf = 0.55
            note = " -- CONFLICTS with hydronic building prior; flagged"
        return {"verdict": "electric-fast", "confidence": conf,
                "reasoning": f"binary gain + median {median:.0f} min to drift 1K "
                             f"(fast<={ht_rules['fast_max_min_to_1k']}); "
                             f"prior={prior}{note}"}
    if barely_drops or (slow and median is not None
                        and median >= 2 * ht_rules["slow_min_min_to_1k"]):
        conf = 0.6 if prior in ("hydronic", "mixed") else 0.5
        return {"verdict": "floor-slow", "confidence": conf,
                "reasoning": f"{(no_drop or 0):.0%} of long windows never drift 1K"
                             f"{f', median {median:.0f} min' if median else ''} -- "
                             f"high-inertia (floor/roof) signature; prior={prior}"}
    if slow:
        conf = 0.75 if prior == "hydronic" else 0.55
        note = " -- CONFLICTS with electric building prior; flagged" \
            if prior == "electric" else ""
        return {"verdict": "hydronic-slow", "confidence": conf,
                "reasoning": f"median {median:.0f} min to drift 1K "
                             f"(slow>={ht_rules['slow_min_min_to_1k']}), "
                             f"regime={regime}; prior={prior}{note}"}
    if fast:
        # Fast drift but non-binary regime: no matching type signature
        # (electric-fast requires binary gain; e.g. Skøyen modulating VAV heat).
        return {"verdict": "ambiguous", "confidence": 0.4,
                "reasoning": f"median {median:.0f} min to drift 1K is fast "
                             f"(<={ht_rules['fast_max_min_to_1k']}) but "
                             f"regime={regime}, not binary -- no matching type "
                             f"signature; prior={prior}"}
    return {"verdict": "ambiguous", "confidence": 0.4,
            "reasoning": f"median {median:.0f} min to drift 1K sits between fast "
                         f"(<={ht_rules['fast_max_min_to_1k']}) and slow "
                         f"(>={ht_rules['slow_min_min_to_1k']}); regime={regime}, "
                         f"prior={prior}"}


def main(argv=None):
    configure_stdout_utf8()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("regimes")
    ap.add_argument("step_summary")
    ap.add_argument("-o", "--out", default=str(Path("runs") / "heating" / "heating_types.jsonl"))
    ap.add_argument("--rules", default=str(DEFAULT_RULES))
    args = ap.parse_args(argv)

    ht = read_json(args.rules)["heating_type"]
    steps = {(s["building"], s["zone"]): s for s in read_jsonl(args.step_summary)}
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    counts = {}
    with open(out_path, "w", encoding="utf-8") as fh:
        for r in read_jsonl(args.regimes):
            res = classify(r, steps.get((r["building"], r["zone"])), ht)
            counts[(r["building"], res["verdict"])] = \
                counts.get((r["building"], res["verdict"]), 0) + 1
            fh.write(json.dumps({
                "building": r["building"], "zone": r["zone"],
                "regime": r["regime"], **res,
            }, ensure_ascii=False) + "\n")
    for b in sorted({b for b, _ in counts}):
        parts = [f"{v}={counts[(b, v)]}" for v in
                 ("electric-fast", "hydronic-slow", "floor-slow", "ambiguous",
                  "excluded") if (b, v) in counts]
        print(f"{b}: " + ", ".join(parts))
    print(f"-> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
