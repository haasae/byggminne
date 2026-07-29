"""Phase 0: verify the timestamps' timezone claim (survey: 'treat as UTC, verify').

Logic: BMS setback schedules run in local wall-clock time (Europe/Oslo). If the
`+00:00` in the zone CSVs is honest UTC, the same local schedule must appear
60 minutes EARLIER in file time during CEST (UTC+2) than during CET (UTC+1).
If the timestamps are actually local time mislabeled as UTC, the modes match.

Cross-check: weather DNI peak hour in June. Solar noon in Aalesund (~6.2 E)
is ~11:35 UTC, ~13:35 CEST -- the peak hour separates the two hypotheses.

    python -m src.heating.tz_check --root knowledge_base/incoming \
        --buildings B07,B01 --zones 4
"""
import argparse
import sys
from collections import Counter
from pathlib import Path

from src.common.io_utils import configure_stdout_utf8
from src.heating.collectief_adapter import discover, weather_path

# DST-safe 2023 windows (transitions: 2023-03-26 and 2023-10-29).
WINTER = ("2023-01-10", "2023-03-20")  # CET, UTC+1
SUMMER = ("2023-04-10", "2023-06-20")  # CEST, UTC+2


def collect_up_steps(path, date_from, date_to):
    """Minute-of-day of every upward setpoint step in [date_from, date_to]."""
    minutes = []
    last_sp = None
    with open(path, "r", encoding="utf-8-sig") as fh:
        fh.readline()
        for line in fh:
            if line.rstrip("\r\n").endswith(",,,"):
                continue
            parts = line.split(",")
            date = parts[0][:10]
            if date < date_from:
                continue
            if date > date_to:
                break
            sp_txt = parts[2]
            if not sp_txt:
                continue
            sp = float(sp_txt)
            if last_sp is not None and sp > last_sp:
                minutes.append(int(parts[0][11:13]) * 60 + int(parts[0][14:16]))
            last_sp = sp
    return minutes


def top_modes(minutes, k=3):
    return Counter(minutes).most_common(k)


def fmt(minute):
    return f"{minute // 60:02d}:{minute % 60:02d}"


def weather_peak_hour(path, month_prefix="2023-06"):
    """Mean DNI by hour-of-day for one month -> (peak_hour, means)."""
    sums = Counter()
    counts = Counter()
    with open(path, "r", encoding="utf-8-sig") as fh:
        header = fh.readline().rstrip("\r\n").split(",")
        dni_col = header.index("ALLSKY_SFC_SW_DNI")
        for line in fh:
            if not line.startswith(month_prefix):
                continue
            parts = line.rstrip("\r\n").split(",")
            try:
                dni = float(parts[dni_col])
            except (ValueError, IndexError):
                continue
            if dni <= -900:  # -999 sentinels
                continue
            hour = int(parts[0][11:13])
            sums[hour] += dni
            counts[hour] += 1
    means = {h: sums[h] / counts[h] for h in counts}
    peak = max(means, key=means.get) if means else None
    return peak, means


def main(argv=None):
    configure_stdout_utf8()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=str(Path("knowledge_base") / "incoming"))
    ap.add_argument("--buildings", default="B07,B01")
    ap.add_argument("--zones", type=int, default=4, help="T-triple zones per building")
    args = ap.parse_args(argv)

    buildings = [b.strip() for b in args.buildings.split(",")]
    verdicts = []
    for b in buildings:
        picked = 0
        for zf in discover(args.root, [b]):
            if zf.kind != "t_triple" or picked >= args.zones:
                continue
            picked += 1
            w = collect_up_steps(zf.path, *WINTER)
            s = collect_up_steps(zf.path, *SUMMER)
            wm, sm = top_modes(w), top_modes(s)
            print(f"{zf.zone}: winter up-steps n={len(w)} modes="
                  f"{[(fmt(m), c) for m, c in wm]} | summer n={len(s)} modes="
                  f"{[(fmt(m), c) for m, c in sm]}")
            if wm and sm:
                shift = wm[0][0] - sm[0][0]
                verdicts.append(shift)
                print(f"  primary-mode shift winter->summer: {shift:+d} min")

    wp = weather_path(args.root)
    if wp.exists():
        peak, means = weather_peak_hour(wp)
        around = {h: round(means.get(h, 0.0), 1) for h in range(9, 16)}
        print(f"\nweather DNI June 2023: peak hour {peak}:00, means 09-15h: {around}")
        print("  UTC predicts peak ~11-12h; local (CEST) predicts ~13-14h")

    if verdicts:
        n_utc = sum(1 for v in verdicts if 45 <= v <= 75)
        n_local = sum(1 for v in verdicts if -15 <= v <= 15)
        print(f"\nzones voting UTC (+60min shift): {n_utc}, "
              f"voting local (no shift): {n_local}, other: "
              f"{len(verdicts) - n_utc - n_local}")
        if n_utc > n_local:
            print("VERDICT: timestamps are UTC (as the +00:00 suffix claims)")
        elif n_local > n_utc:
            print("VERDICT: timestamps are LOCAL wall-clock mislabeled as UTC")
        else:
            print("VERDICT: inconclusive -- inspect modes above")
    return 0


if __name__ == "__main__":
    sys.exit(main())
