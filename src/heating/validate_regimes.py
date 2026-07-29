"""Phase 2: triple-validate the regime classification (plan section: Phase 2).

Three channels, three severities:
- PINNED (hard-fail): the survey's individually measured zones must reproduce.
- PRIORS (warn only): per-building regime distributions vs building metadata.
  The survey sampled 3 zones/building -- a surprising zone is a finding to
  record in data_observations.md, not a failure.
- PHYSICS (hard-fail): heating-season duty cycle must correlate NEGATIVELY
  with outdoor temperature (sign, not magnitude); plus a meter cross-check for
  the all-electric buildings only (B03/B05/B07: building duty cycle vs main
  kWh must correlate positively).

    python -m src.heating.validate_regimes runs/heating/regimes.jsonl \
        --proxy-dir runs/heating/proxy -o runs/heating/validate_report.md
"""
import argparse
import sys
from pathlib import Path

from src.common.io_utils import configure_stdout_utf8, read_json, read_jsonl
from src.heating.build_zone_table import DEFAULT_RULES
from src.heating.collectief_adapter import read_meter_daily, read_weather_daily
from src.heating.energy_proxy import read_daily_duty, zone_orientation
from src.profile.seasonal_check import pearson

# Survey pins (knowledge_base/collectief_survey.md, individually measured).
PINNED = [
    ("B01", "B01-MA-A-1-21", "modulating"),
    ("B07", "B07-MA-A-1-12", "dead"),
    ("B07", "B07-MA-A-1-13", "dead"),
    ("B06", "B06-MA-A-1-13", "no_data"),
]
PINNED_BOTH_REGIMES = "B04"  # survey: B04 shows binary AND modulating zones

# Warn-level priors: building -> regime expected to dominate t_triple zones.
PRIORS = {"B01": "modulating", "B02": "binary", "B03": "binary",
          "B04": None, "B05": "binary", "B06": "binary", "B07": "binary"}

# Meter cross-check only where ALL heat crosses the electric main:
# B06 = district heat, B01/B02/B04 = heat-pump/submeter mixes (survey).
ALL_ELECTRIC = ["B03", "B05", "B07"]


def in_heating_season(date, mean_temp, rules):
    hs = rules["heating_season"]
    return int(date[5:7]) in hs["months"] and mean_temp < hs["daily_mean_outdoor_max_c"]


def check_pinned(regimes):
    errors = []
    by_key = {(r["building"], r["zone"]): r["regime"] for r in regimes}
    present = {r["building"] for r in regimes}
    for b, zone, expected in PINNED:
        if b not in present:
            continue
        got = by_key.get((b, zone))
        if got != expected:
            errors.append(f"PINNED {zone}: expected {expected}, got {got}")
    if PINNED_BOTH_REGIMES in present:
        b04 = {r["regime"] for r in regimes if r["building"] == PINNED_BOTH_REGIMES}
        if not {"binary", "modulating"} <= b04:
            errors.append(f"PINNED {PINNED_BOTH_REGIMES}: expected both binary and "
                          f"modulating zones, got {sorted(b04)}")
    return errors


def check_priors(regimes):
    warnings = []
    per_b = {}
    for r in regimes:
        per_b.setdefault(r["building"], []).append(r["regime"])
    for b, rs in sorted(per_b.items()):
        expected = PRIORS.get(b)
        if not expected:
            continue
        live = [x for x in rs if x in ("binary", "modulating", "mixed")]
        if not live:
            warnings.append(f"PRIOR {b}: no live zones classified")
            continue
        share = live.count(expected) / len(live)
        if share < 0.5:
            warnings.append(
                f"PRIOR {b}: expected {expected}-majority, got "
                f"{share:.0%} ({live.count(expected)}/{len(live)}) -- a finding "
                f"to record, not necessarily an error")
    return warnings


def check_physics(buildings, proxy_dir, weather_daily, rules, orientations=None):
    """Heating-season daily duty vs outdoor temp: Pearson must be negative.

    Gated on heating-oriented zones only: a T_Gain that is busiest in summer
    is a cooling actuator regardless of its header (the B04 finding) and must
    not vote on the HEATING physics check.
    """
    errors, lines = [], []
    for b in sorted(buildings):
        path = proxy_dir / f"{b}.csv"
        if not path.exists():
            errors.append(f"PHYSICS {b}: proxy file missing ({path})")
            continue
        include = None
        if orientations and b in orientations:
            include = {z for z, o in orientations[b].items()
                       if o["orientation"] == "heating"}
            if not include:
                lines.append(f"{b}: no heating-oriented zones -- physics check skipped")
                continue
        duty = read_daily_duty(path, include)
        season = {d: v for d, v in duty.items()
                  if d in weather_daily and in_heating_season(d, weather_daily[d], rules)}
        temp = {d: weather_daily[d] for d in season}
        r, n = pearson(season, temp)
        lines.append(f"{b}: duty-vs-outdoor-temp r={r if r is None else round(r, 3)} "
                     f"(n={n} heating-season days)")
        if r is None or n < 30:
            errors.append(f"PHYSICS {b}: correlation undefined or too few days (n={n})")
        elif r >= 0:
            errors.append(f"PHYSICS {b}: duty cycle correlates POSITIVELY with "
                          f"outdoor temp (r={r:.3f}) -- heating hypothesis violated")
    return errors, lines


def check_meters(buildings, proxy_dir, root, weather_daily, rules, includes=None):
    """All-electric buildings: daily duty vs main kWh must correlate positively."""
    errors, lines = [], []
    for b in [x for x in ALL_ELECTRIC if x in buildings]:
        path = proxy_dir / f"{b}.csv"
        if not path.exists():
            continue
        duty = read_daily_duty(path, includes.get(b) if includes else None)
        try:
            kwh = read_meter_daily(root, b)
        except (FileNotFoundError, ValueError) as exc:
            errors.append(f"METER {b}: cannot read meter ({exc})")
            continue
        season = {d: v for d, v in duty.items()
                  if d in kwh and d in weather_daily
                  and in_heating_season(d, weather_daily[d], rules)}
        r, n = pearson(season, {d: kwh[d] for d in season})
        lines.append(f"{b}: duty-vs-main-kWh r={r if r is None else round(r, 3)} "
                     f"(n={n} heating-season days)")
        if r is None or n < 30:
            errors.append(f"METER {b}: correlation undefined or too few days (n={n})")
        elif r <= 0:
            errors.append(f"METER {b}: duty does not track electric main "
                          f"(r={r:.3f}) -- proxy or classification suspect")
    return errors, lines


def main(argv=None):
    configure_stdout_utf8()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("regimes")
    ap.add_argument("--proxy-dir", default=str(Path("runs") / "heating" / "proxy"))
    ap.add_argument("--root", default=str(Path("knowledge_base") / "incoming"))
    ap.add_argument("--rules", default=str(DEFAULT_RULES))
    ap.add_argument("-o", "--out", default=str(Path("runs") / "heating" / "validate_report.md"))
    ap.add_argument("--orientation-out",
                    default=str(Path("runs") / "heating" / "orientation.jsonl"))
    ap.add_argument("--skip-physics", action="store_true",
                    help="pinned+priors only (no proxy/weather/meter files needed)")
    args = ap.parse_args(argv)

    rules = read_json(args.rules)
    regimes = read_jsonl(args.regimes)
    buildings = sorted({r["building"] for r in regimes})

    errors = check_pinned(regimes)
    warnings = check_priors(regimes)
    detail = []
    orient_summary = []
    if not args.skip_physics:
        weather_daily = read_weather_daily(args.root)
        # Thermal orientation per zone (heating/cooling/dual/idle from
        # seasonal duty) -- persisted for downstream consumers.
        orientations = {}
        for b in buildings:
            path = Path(args.proxy_dir) / f"{b}.csv"
            if path.exists():
                orientations[b] = zone_orientation(path, rules["orientation"])
        orient_path = Path(args.orientation_out)
        orient_path.parent.mkdir(parents=True, exist_ok=True)
        import json as _json
        with open(orient_path, "w", encoding="utf-8") as fh:
            for b, zones in sorted(orientations.items()):
                for z, o in sorted(zones.items()):
                    fh.write(_json.dumps({"building": b, "zone": z, **o},
                                         ensure_ascii=False) + "\n")
        for b, zones in sorted(orientations.items()):
            counts = {}
            for o in zones.values():
                counts[o["orientation"]] = counts.get(o["orientation"], 0) + 1
            orient_summary.append(f"{b}: " + ", ".join(
                f"{k}={v}" for k, v in sorted(counts.items())))
            non_heating = sum(v for k, v in counts.items()
                              if k in ("cooling", "dual"))
            if non_heating > len(zones) * 0.2:
                warnings.append(
                    f"ORIENTATION {b}: {non_heating}/{len(zones)} T_Gain zones "
                    f"are cooling/dual-oriented -- header says heating, data "
                    f"disagrees; excluded from heating physics + flexibility")
        includes = {b: {z for z, o in zones.items() if o["orientation"] == "heating"}
                    for b, zones in orientations.items()}
        e1, l1 = check_physics(buildings, Path(args.proxy_dir), weather_daily,
                               rules, orientations)
        e2, l2 = check_meters(buildings, Path(args.proxy_dir), args.root,
                              weather_daily, rules, includes)
        errors += e1 + e2
        detail = l1 + l2

    report = ["# Regime validation report", ""]
    report += [f"- buildings: {', '.join(buildings)}"]
    if orient_summary:
        report += ["", "## Thermal orientation (from seasonal duty)", ""] + \
                  [f"- {x}" for x in orient_summary]
    report += ["", "## Correlations (heating-oriented zones only)", ""] + \
              [f"- {x}" for x in detail]
    report += ["", "## Hard failures", ""] + ([f"- {x}" for x in errors] or ["- none"])
    report += ["", "## Warnings (findings, not failures)", ""] + \
              ([f"- {x}" for x in warnings] or ["- none"])
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(report) + "\n", encoding="utf-8")

    for x in errors:
        print(f"FAIL {x}")
    for x in warnings:
        print(f"WARN {x}")
    print(f"validation: {'FAILED' if errors else 'OK'} "
          f"({len(errors)} errors, {len(warnings)} warnings) -> {out}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
