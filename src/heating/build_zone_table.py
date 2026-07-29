"""Build the canonical per-zone table (Phase 1) -- one JSON line per zone CSV.

One streamed pass per file; a scan cache keyed on (path, size, mtime) makes
re-runs file-granular resumable (only new/changed files are re-read). Also
doubles as the Phase 0 timing benchmark via the summary line.

    python -m src.heating.build_zone_table --root knowledge_base/incoming \
        --buildings B07,B02 -o runs/heating/zone_table.jsonl [--progress]
    python -m src.heating.build_zone_table --check-survey runs/heating/zone_table.jsonl
"""
import argparse
import json
import sys
import time
from pathlib import Path

from src.common.io_utils import configure_stdout_utf8, read_json, read_jsonl
from src.heating.collectief_adapter import discover
from src.heating.triple_stats import TripleAccumulator

DEFAULT_RULES = Path("knowledge_base") / "heating_rules.json"


def _parse(txt):
    return float(txt) if txt else None


def scan_triple_file(path):
    """Stream one T-triple CSV -> stats row. Fast path skips empty grid rows."""
    acc = TripleAccumulator()
    with open(path, "r", encoding="utf-8-sig") as fh:
        fh.readline()  # header
        for line in fh:
            line = line.rstrip("\r\n")
            if line.endswith(",,,"):
                acc.add_empty()
                continue
            parts = line.split(",")
            try:
                acc.add(parts[0], _parse(parts[1]), _parse(parts[2]), _parse(parts[3]))
            except (ValueError, IndexError):
                acc.n_bad += 1
                acc.n_grid += 1
    return acc.row()


def scan_other_file(path, n_cols):
    """Light scan for non-triple files: window + row counts only."""
    empty_suffix = "," * (n_cols - 1)
    n_grid = n_data = 0
    first_ts = last_ts = None
    with open(path, "r", encoding="utf-8-sig") as fh:
        fh.readline()
        for line in fh:
            line = line.rstrip("\r\n")
            n_grid += 1
            if line.endswith(empty_suffix):
                continue
            n_data += 1
            ts = line[: line.find(",")]
            if first_ts is None:
                first_ts = ts
            last_ts = ts
    return {
        "n_grid": n_grid,
        "n_data": n_data,
        "first_data_ts": first_ts,
        "last_data_ts": last_ts,
    }


def apply_flags(row, rules):
    """Derive quality flags from a scanned row (t_triple only gets the full set)."""
    flags = []
    if row["stats"].get("n_data", 0) == 0:
        flags.append("empty")
    if row["kind"] == "t_triple" and row["stats"]["n_data"] > 0:
        gain = row["stats"]["gain"]
        if gain.get("n", 0) > 0 and gain.get("max") == rules["dead_gain"]["max_value"]:
            flags.append("dead_gain")
        t = row["stats"]["t"]
        stuck = rules["stuck_sensor"]
        if t.get("n", 0) >= stuck["min_rows"] and (
            (t.get("distinct") is not None and t["distinct"] <= stuck["max_distinct"])
            or t.get("std", 1.0) <= stuck["max_std"]
        ):
            flags.append("stuck_sensor_suspect")
        if row["stats"]["sp"].get("levels") is None and row["stats"]["sp"].get("n", 0):
            flags.append("sp_levels_capped")
    row["flags"] = flags
    return row


def load_cache(cache_path):
    cache = {}
    if cache_path.exists():
        for entry in read_jsonl(cache_path):
            cache[entry["path"]] = entry
    return cache


def build(root, buildings, out_path, cache_path, rules, progress=False):
    cache = load_cache(cache_path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    t0 = time.monotonic()
    total_bytes = total_rows = n_cached = 0
    with open(cache_path, "a", encoding="utf-8") as cache_fh:
        for zf in discover(root, buildings):
            stat = zf.path.stat()
            key = str(zf.path.resolve())
            hit = cache.get(key)
            if hit and hit["size"] == stat.st_size and hit["mtime"] == stat.st_mtime:
                rows.append(hit["row"])
                n_cached += 1
                continue
            t_file = time.monotonic()
            if zf.kind == "t_triple":
                stats = scan_triple_file(zf.path)
            else:
                stats = scan_other_file(zf.path, len(zf.columns))
            row = apply_flags(
                {
                    "building": zf.building,
                    "zone": zf.zone,
                    "file": zf.path.name,
                    "kind": zf.kind,
                    "columns": zf.columns,
                    "stats": stats,
                },
                rules,
            )
            rows.append(row)
            entry = {"path": key, "size": stat.st_size, "mtime": stat.st_mtime, "row": row}
            cache_fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            cache_fh.flush()
            total_bytes += stat.st_size
            total_rows += stats["n_grid"]
            if progress:
                dt = time.monotonic() - t_file
                print(f"  {zf.building}/{zf.zone} [{zf.kind}] "
                      f"{stats['n_grid']:,} rows in {dt:.1f}s", flush=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    elapsed = time.monotonic() - t0
    print(
        f"{len(rows)} zones ({n_cached} cached) | {total_rows:,} rows, "
        f"{total_bytes / 1e6:,.0f} MB scanned in {elapsed:,.1f}s"
        + (f" | {total_rows / elapsed:,.0f} rows/s, {total_bytes / 1e6 / elapsed:.1f} MB/s"
           if elapsed > 0 and total_rows else "")
    )
    return rows


# --- survey verification (knowledge_base/collectief_survey.md, measured facts) ---

SURVEY_T_TRIPLES = {"B01": 244, "B02": 18, "B03": 65, "B04": 214,
                    "B05": 78, "B06": 133, "B07": 32}
SURVEY_DEAD_GAIN = {("B07", "B07-MA-A-1-12"), ("B07", "B07-MA-A-1-13")}
SURVEY_EMPTY = {("B06", "B06-MA-A-1-13")}
SURVEY_ORPHAN = ("B01", "B01-MA-A-B-3")  # COOL header despite T-zone-style name


def check_survey(rows):
    """Assert the survey's measured facts for every building present. -> error list"""
    errors = []
    present = {r["building"] for r in rows}
    counts = {}
    for r in rows:
        if r["kind"] == "t_triple":
            counts[r["building"]] = counts.get(r["building"], 0) + 1
    for b in sorted(present):
        exp = SURVEY_T_TRIPLES.get(b)
        if exp is not None and counts.get(b, 0) != exp:
            errors.append(f"{b}: {counts.get(b, 0)} t_triples, survey says {exp}")
    by_key = {(r["building"], r["zone"]): r for r in rows}
    for key in SURVEY_DEAD_GAIN:
        if key[0] in present:
            r = by_key.get(key)
            if r is None or "dead_gain" not in r.get("flags", []):
                errors.append(f"{key[1]}: expected dead_gain flag")
    for key in SURVEY_EMPTY:
        if key[0] in present:
            r = by_key.get(key)
            if r is None or "empty" not in r.get("flags", []):
                errors.append(f"{key[1]}: expected empty flag")
    if SURVEY_ORPHAN[0] in present:
        r = by_key.get(SURVEY_ORPHAN)
        if r is None:
            errors.append(f"{SURVEY_ORPHAN[1]}: orphan file missing from table")
        elif r["kind"] == "t_triple":
            errors.append(f"{SURVEY_ORPHAN[1]}: dispatched as t_triple, header says COOL")
    return errors


def main(argv=None):
    configure_stdout_utf8()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=str(Path("knowledge_base") / "incoming"))
    ap.add_argument("--buildings", help="comma list, e.g. B07,B02 (default: all)")
    ap.add_argument("-o", "--out", default=str(Path("runs") / "heating" / "zone_table.jsonl"))
    ap.add_argument("--cache", default=str(Path("runs") / "heating" / "scan_cache.jsonl"))
    ap.add_argument("--rules", default=str(DEFAULT_RULES))
    ap.add_argument("--progress", action="store_true")
    ap.add_argument("--check-survey", metavar="TABLE",
                    help="verify an existing zone table against the survey facts and exit")
    args = ap.parse_args(argv)

    if args.check_survey:
        errors = check_survey(read_jsonl(args.check_survey))
        for e in errors:
            print(f"FAIL {e}")
        print("survey check: " + ("FAILED" if errors else "OK"))
        return 1 if errors else 0

    rules = read_json(args.rules)
    buildings = [b.strip() for b in args.buildings.split(",")] if args.buildings else None
    build(args.root, buildings, Path(args.out), Path(args.cache), rules,
          progress=args.progress)
    return 0


if __name__ == "__main__":
    sys.exit(main())
