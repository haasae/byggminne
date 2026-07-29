"""Phase 2: per-zone hourly energy proxy (gain mean + sample count).

The gain is the nearest per-room energy stand-in: duty cycle for binary zones,
valve position for modulating ones -- numerically the same hourly mean, named
by the regime downstream. Coverage (n samples/hour) is emitted alongside so
the 39-46% missing data can never hide inside a bare mean.

Output: one long-format CSV per building, runs/heating/proxy/B0X.csv with
rows `zone,hour_utc,mean_gain,n`. Zones already present in the output are
skipped on re-run (file-granular resumability, same idea as the scan cache).

    python -m src.heating.energy_proxy --buildings B07 [--root ...] [--out-dir ...]
"""
import argparse
import json
import sys
from pathlib import Path

from src.common.io_utils import configure_stdout_utf8, read_json
from src.heating.collectief_adapter import discover


def hourly_means(path):
    """Stream one T-triple CSV -> list of (hour 'YYYY-MM-DD HH', mean, n)."""
    out = []
    cur_hour = None
    cur_sum = 0.0
    cur_n = 0
    with open(path, "r", encoding="utf-8-sig") as fh:
        fh.readline()
        for line in fh:
            line = line.rstrip("\r\n")
            if line.endswith(",,,"):
                continue
            parts = line.split(",")
            g = parts[3]
            if not g:
                continue
            hour = parts[0][:13]  # 'YYYY-MM-DD HH' (grid is time-sorted)
            if hour != cur_hour:
                if cur_n:
                    out.append((cur_hour, cur_sum / cur_n, cur_n))
                cur_hour, cur_sum, cur_n = hour, 0.0, 0
            try:
                cur_sum += float(g)
                cur_n += 1
            except ValueError:
                continue
    if cur_n:
        out.append((cur_hour, cur_sum / cur_n, cur_n))
    return out


def existing_zones(csv_path):
    zones = set()
    if csv_path.exists():
        with open(csv_path, "r", encoding="utf-8") as fh:
            fh.readline()
            for line in fh:
                zones.add(line[: line.find(",")])
    return zones


def build_proxy(root, buildings, out_dir, progress=False):
    out_dir.mkdir(parents=True, exist_ok=True)
    per_building = {}
    for zf in discover(root, buildings):
        if zf.kind != "t_triple":
            continue
        per_building.setdefault(zf.building, []).append(zf)
    for building, zfs in sorted(per_building.items()):
        csv_path = out_dir / f"{building}.csv"
        done = existing_zones(csv_path)
        todo = [zf for zf in zfs if zf.zone not in done]
        if not todo:
            if progress:
                print(f"{building}: all {len(zfs)} zones already in {csv_path.name}")
            continue
        new_file = not csv_path.exists()
        with open(csv_path, "a", encoding="utf-8") as fh:
            if new_file:
                fh.write("zone,hour_utc,mean_gain,n\n")
            for zf in todo:
                for hour, mean, n in hourly_means(zf.path):
                    fh.write(f"{zf.zone},{hour},{mean:.4f},{n}\n")
                fh.flush()
                if progress:
                    print(f"  {zf.zone} done", flush=True)
        print(f"{building}: +{len(todo)} zones ({len(done)} already present) -> {csv_path}")


def read_daily_duty(csv_path, include=None):
    """Proxy CSV -> {date: coverage-weighted mean gain}. include = zone filter."""
    sums, counts = {}, {}
    with open(csv_path, "r", encoding="utf-8") as fh:
        fh.readline()
        for line in fh:
            parts = line.rstrip("\r\n").split(",")
            if include is not None and parts[0] not in include:
                continue
            date = parts[1][:10]
            n = int(parts[3])
            sums[date] = sums.get(date, 0.0) + float(parts[2]) * n
            counts[date] = counts.get(date, 0) + n
    return {d: sums[d] / counts[d] for d in sums}


def zone_orientation(csv_path, orient_rules):
    """Proxy CSV -> {zone: {winter_duty, summer_duty, orientation}}.

    Orientation from seasonal duty: a 'T_Gain' busiest in summer is a cooling
    actuator no matter what the header says (the B04 finding, 2026-07-23:
    125/209 zones summer-dominant in the fan-coil building).
    """
    win = {m: True for m in orient_rules["winter_months"]}
    sum_ = {m: True for m in orient_rules["summer_months"]}
    acc = {}
    with open(csv_path, "r", encoding="utf-8") as fh:
        fh.readline()
        for line in fh:
            parts = line.rstrip("\r\n").split(",")
            month = int(parts[1][5:7])
            season = "w" if month in win else ("s" if month in sum_ else None)
            if season is None:
                continue
            z = acc.setdefault(parts[0], {"w": [0.0, 0], "s": [0.0, 0]})
            n = int(parts[3])
            z[season][0] += float(parts[2]) * n
            z[season][1] += n
    out = {}
    thr = orient_rules["min_active_duty_pct"]
    ratio = orient_rules["dominance_ratio"]
    for zone, z in acc.items():
        wd = z["w"][0] / z["w"][1] if z["w"][1] else 0.0
        sd = z["s"][0] / z["s"][1] if z["s"][1] else 0.0
        # Dominance, not mere activity: Aalesund summer nights are cold, so
        # genuine heating runs a little in summer too. Only a zone whose gain
        # is clearly BUSIER in summer is a mislabeled cooling actuator.
        if wd < thr and sd < thr:
            orientation = "idle"
        elif sd > wd * ratio and sd >= thr:
            orientation = "cooling"
        elif wd > sd * ratio:
            orientation = "heating"
        else:
            orientation = "dual"
        out[zone] = {"winter_duty": round(wd, 2), "summer_duty": round(sd, 2),
                     "orientation": orientation}
    return out


def write_orientation(out_dir, orientation_out, rules_path):
    """Write orientation.jsonl from all proxy CSVs in out_dir.

    Same row shape validate_regimes.py emits, but with no weather/meter
    dependency -- for datasets without a Weather/ folder (e.g. Skøyen).
    """
    orient_rules = read_json(rules_path)["orientation"]
    out_path = Path(orientation_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(out_path, "w", encoding="utf-8") as fh:
        for csv_path in sorted(Path(out_dir).glob("*.csv")):
            building = csv_path.stem
            for zone, o in sorted(zone_orientation(csv_path, orient_rules).items()):
                fh.write(json.dumps({"building": building, "zone": zone, **o},
                                    ensure_ascii=False) + "\n")
                n += 1
    print(f"{n} zone orientations -> {out_path}")


def main(argv=None):
    configure_stdout_utf8()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=str(Path("knowledge_base") / "incoming"))
    ap.add_argument("--buildings", help="comma list (default: all)")
    ap.add_argument("--out-dir", default=str(Path("runs") / "heating" / "proxy"))
    ap.add_argument("--orientation-out",
                    help="also write orientation.jsonl (from the proxy CSVs)")
    ap.add_argument("--rules",
                    default=str(Path("knowledge_base") / "heating_rules.json"))
    ap.add_argument("--progress", action="store_true")
    args = ap.parse_args(argv)
    buildings = [b.strip() for b in args.buildings.split(",")] if args.buildings else None
    build_proxy(args.root, buildings, Path(args.out_dir), progress=args.progress)
    if args.orientation_out:
        write_orientation(Path(args.out_dir), args.orientation_out, args.rules)
    return 0


if __name__ == "__main__":
    sys.exit(main())
