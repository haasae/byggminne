"""Phase 3: mine setpoint-setback decay events -> thermal response per zone.

The schedule-stepped setpoints are natural experiments: a setback (setpoint
drop) with the heater observed OFF gives a free-decay window whose speed is
the zone's thermal signature (electric fast, waterborne slow -- the advisor's
RC intuition, measured model-free).

Events are keyed on setpoint drop PLUS observed gain shutoff (in binary zones
temperature never tracks the setpoint tightly, so setpoint-only windows
mis-frame the decay). Per event: minutes to drift 1 K, drift slope over the
first hour, drop at 2 h, and a time-to-63% proxy when the window reaches a
plateau. Offsets are counted in grid lines (the padded grid is 1 row/minute).

    python -m src.heating.step_response --buildings B07 [--force]
"""
import argparse
import json
import statistics
import sys
from pathlib import Path

from src.common.io_utils import configure_stdout_utf8, read_json, read_jsonl
from src.heating.build_zone_table import DEFAULT_RULES
from src.heating.collectief_adapter import discover, read_weather_daily


def season_of(date):
    """'2023-01-15' -> '2022-23' (heating seasons run Aug..Jul)."""
    y, m = int(date[:4]), int(date[5:7])
    start = y if m >= 8 else y - 1
    return f"{start}-{str(start + 1)[2:]}"


def outdoor_bin(temp, edges):
    if temp is None:
        return None
    for edge in edges:
        if temp < edge:
            return f"<{edge}"
    return f">={edges[-1]}"


class _Event:
    """One open decay window; collects (minute_offset, T) samples."""

    def __init__(self, i0, ts0, sp_from, sp_to, t0):
        self.i0 = i0
        self.ts0 = ts0
        self.sp_from = sp_from
        self.sp_to = sp_to
        self.t0 = t0
        self.samples = []          # (offset_min, T)
        self.early_gains = []      # gain samples in the first 15 min
        self.consec_on = 0
        self.reheat = False


def _finish(ev, sr):
    """Close an event -> metrics dict, or None if it never qualified."""
    if ev.t0 is None or len(ev.samples) < 5:
        return None
    # Free decay requires the heater actually off early in the window.
    if ev.early_gains and (sum(ev.early_gains) / len(ev.early_gains)) > sr["gain_off_pct"]:
        return None
    t0 = ev.t0
    drop_1k = next((off for off, t in ev.samples if t <= t0 - 1.0), None)
    # Slope over the first hour, least squares (needs >=5 points).
    first = [(off, t) for off, t in ev.samples if off <= 60]
    slope = None
    if len(first) >= 5:
        n = len(first)
        mx = sum(o for o, _ in first) / n
        my = sum(t for _, t in first) / n
        sxx = sum((o - mx) ** 2 for o, _ in first)
        if sxx:
            slope = sum((o - mx) * (t - my) for o, t in first) / sxx * 60  # K/h
    near_2h = [s for s in ev.samples if 105 <= s[0] <= 135]
    drop_2h = round(t0 - near_2h[-1][1], 3) if near_2h else None
    # t63 only when the window plateaus (>=min window, real total drop).
    t63 = None
    last_off = ev.samples[-1][0]
    if last_off >= sr["min_window_for_t63_min"]:
        tail = [t for off, t in ev.samples if off >= last_off - 30]
        plateau = sum(tail) / len(tail)
        total = t0 - plateau
        if total >= sr["plateau_min_drop_c"]:
            target = t0 - 0.632 * total
            t63 = next((off for off, t in ev.samples if t <= target), None)
    return {
        "ts": ev.ts0,
        "sp_from": ev.sp_from,
        "sp_to": ev.sp_to,
        "t_start": round(t0, 3),
        "minutes_to_1k": drop_1k,
        "slope_first_hour_k_per_h": None if slope is None else round(slope, 3),
        "drop_at_2h": drop_2h,
        "t63_minutes": t63,
        "window_min": last_off,
        "reheat_interrupt": ev.reheat,
        "season": season_of(ev.ts0[:10]),
    }


def mine_events(path, sr):
    """Stream one T-triple CSV -> list of event metric dicts."""
    events = []
    ev = None
    last_sp = None
    last_t = None
    i = 0  # grid line index == minutes since file start (padded 1-min grid)
    with open(path, "r", encoding="utf-8-sig") as fh:
        fh.readline()
        for line in fh:
            i += 1
            line = line.rstrip("\r\n")
            if line.endswith(",,,"):
                continue
            parts = line.split(",")
            try:
                t = float(parts[1]) if parts[1] else None
                sp = float(parts[2]) if parts[2] else None
                g = float(parts[3]) if parts[3] else None
            except (ValueError, IndexError):
                continue

            if ev is not None:
                off = i - ev.i0
                closed = False
                if off > sr["max_window_min"]:
                    closed = True
                elif sp is not None and sp > ev.sp_to + 0.1:  # schedule moved on
                    closed = True
                if g is not None:
                    if off <= 15:
                        ev.early_gains.append(g)
                    if g >= sr["gain_on_abort_pct"]:
                        ev.consec_on += 1
                        if ev.consec_on >= 2:  # heater genuinely back on
                            ev.reheat = True
                            closed = True
                    else:
                        ev.consec_on = 0
                if not closed and t is not None:
                    ev.samples.append((off, t))
                if closed:
                    row = _finish(ev, sr)
                    if row:
                        events.append(row)
                    ev = None

            if (ev is None and sp is not None and last_sp is not None
                    and last_sp - sp >= sr["min_sp_drop_c"]):
                ev = _Event(i, parts[0], last_sp, sp, t if t is not None else last_t)
            if sp is not None:
                last_sp = sp
            if t is not None:
                last_t = t
    if ev is not None:
        row = _finish(ev, sr)
        if row:
            events.append(row)
    return events


def _quartiles(values):
    if not values:
        return None
    if len(values) < 4:
        m = statistics.median(values)
        return {"n": len(values), "median": m, "iqr": None}
    q = statistics.quantiles(values, n=4)
    return {"n": len(values), "median": round(q[1], 1), "iqr": round(q[2] - q[0], 1)}


def summarize_zone(building, zone, events, weather_daily, sr):
    """Events -> one summary row (pooled + per season + per outdoor bin)."""
    for e in events:
        temp = weather_daily.get(e["ts"][:10])
        e["outdoor_temp"] = None if temp is None else round(temp, 1)
        e["outdoor_bin"] = outdoor_bin(temp, sr["outdoor_bins_c"])
    m1k = [e["minutes_to_1k"] for e in events if e["minutes_to_1k"] is not None]
    no_drop = sum(1 for e in events if e["minutes_to_1k"] is None
                  and e["window_min"] >= 120 and not e["reheat_interrupt"])
    eligible = no_drop + len(m1k)
    row = {
        "building": building,
        "zone": zone,
        "n_events": len(events),
        "minutes_to_1k": _quartiles(m1k),
        "no_1k_drop_share": round(no_drop / eligible, 3) if eligible else None,
        "slope_first_hour": _quartiles(
            [e["slope_first_hour_k_per_h"] for e in events
             if e["slope_first_hour_k_per_h"] is not None]),
        "t63": _quartiles([e["t63_minutes"] for e in events
                           if e["t63_minutes"] is not None]),
        "by_season": {}, "by_outdoor_bin": {},
    }
    for key, field in (("by_season", "season"), ("by_outdoor_bin", "outdoor_bin")):
        groups = {}
        for e in events:
            k = e[field]
            if k is not None and e["minutes_to_1k"] is not None:
                groups.setdefault(k, []).append(e["minutes_to_1k"])
        row[key] = {k: _quartiles(v) for k, v in sorted(groups.items())}
    return row


def render_report(summaries, out_path):
    lines = ["# Step-response report (Phase 3)", ""]
    per_b = {}
    for s in summaries:
        if s["minutes_to_1k"]:
            per_b.setdefault(s["building"], []).append(s["minutes_to_1k"]["median"])
    lines += ["| building | zones w/ tau | median minutes-to-1K (of zone medians) |",
              "|---|---|---|"]
    for b, meds in sorted(per_b.items()):
        lines.append(f"| {b} | {len(meds)} | {statistics.median(meds):.0f} |")
    # Pre-registered prediction (advisor): electric B05/B07 faster than
    # hydronic B01/B02. Recorded either way; a negative result is a finding.
    el = [m for b in ("B05", "B07") for m in per_b.get(b, [])]
    hy = [m for b in ("B01", "B02") for m in per_b.get(b, [])]
    if el and hy:
        e_med, h_med = statistics.median(el), statistics.median(hy)
        verdict = "CONFIRMED" if e_med < h_med else "REJECTED"
        lines += ["", f"## Pre-registered prediction: electric (B05/B07) faster "
                      f"than hydronic (B01/B02): **{verdict}**",
                  f"- electric median minutes-to-1K: {e_med:.0f} (n={len(el)} zones)",
                  f"- hydronic median minutes-to-1K: {h_med:.0f} (n={len(hy)} zones)"]
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None):
    configure_stdout_utf8()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=str(Path("knowledge_base") / "incoming"))
    ap.add_argument("--buildings", help="comma list (default: all)")
    ap.add_argument("--events-dir", default=str(Path("runs") / "heating" / "step_events"))
    ap.add_argument("--summary", default=str(Path("runs") / "heating" / "step_summary.jsonl"))
    ap.add_argument("--report", default=str(Path("runs") / "heating" / "step_response_report.md"))
    ap.add_argument("--rules", default=str(DEFAULT_RULES))
    ap.add_argument("--force", action="store_true", help="re-mine existing buildings")
    ap.add_argument("--progress", action="store_true")
    args = ap.parse_args(argv)

    rules = read_json(args.rules)
    sr = rules["step_response"]
    try:
        weather_daily = read_weather_daily(args.root)
    except FileNotFoundError:
        weather_daily = {}
    events_dir = Path(args.events_dir)
    events_dir.mkdir(parents=True, exist_ok=True)
    buildings = [b.strip() for b in args.buildings.split(",")] if args.buildings else None

    per_building = {}
    for zf in discover(args.root, buildings):
        if zf.kind == "t_triple":
            per_building.setdefault(zf.building, []).append(zf)

    for b, zfs in sorted(per_building.items()):
        out = events_dir / f"{b}.jsonl"
        if out.exists() and not args.force:
            print(f"{b}: events exist, skipping (--force to re-mine)")
            continue
        with open(out, "w", encoding="utf-8") as fh:
            for zf in zfs:
                events = mine_events(zf.path, sr)
                for e in events:
                    fh.write(json.dumps({"building": b, "zone": zf.zone, **e},
                                        ensure_ascii=False) + "\n")
                if args.progress:
                    print(f"  {zf.zone}: {len(events)} events", flush=True)
        print(f"{b}: mined -> {out}")

    # Summary + report are rebuilt from ALL event files present (cheap).
    summaries = []
    for f in sorted(events_dir.glob("*.jsonl")):
        by_zone = {}
        for e in read_jsonl(f):
            by_zone.setdefault((e["building"], e["zone"]), []).append(e)
        for (b, z), evs in sorted(by_zone.items()):
            summaries.append(summarize_zone(b, z, evs, weather_daily, sr))
    summary_path = Path(args.summary)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with open(summary_path, "w", encoding="utf-8") as fh:
        for s in summaries:
            fh.write(json.dumps(s, ensure_ascii=False) + "\n")
    render_report(summaries, Path(args.report))
    print(f"{len(summaries)} zone summaries -> {summary_path}; report -> {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
