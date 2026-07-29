"""One-off probe: r/y/u control-loop behaviour for selected COLLECTiEF zones.

r = T_Setvalue (setpoint), y = T_Actualvalue (zone temp), u = T_Gain (0-100%).
Per zone: setpoint tracking error, heater-ON rise response (gain + time
constant), and control-signal saturation/oscillation stats -- each compared
against the facts already stored on the Zone node (tauMedianMin, regime).

    python -m src.heating.ryu_probe --zones B05:B05-MA-A-2-35,B01:B01-MA-C-1-98
    python -m src.heating.ryu_probe --demo    # self-check, no dataset needed

Report + PNGs -> runs/heating/ryu/. Read-only on the dataset and the graph.
"""
import argparse
import json
import statistics
import sys
from datetime import datetime, timedelta
from pathlib import Path

from src.common.io_utils import configure_stdout_utf8, read_jsonl

DEFAULT_ROOT = Path('knowledge_base') / 'incoming'
DEFAULT_RUNS = Path('runs') / 'heating'
DEFAULT_OUT = Path('runs') / 'heating' / 'ryu'

WINTER_MONTHS = {10, 11, 12, 1, 2, 3}


def load_series(csv_path):
    """Stream one T-triple CSV -> (t0 datetime, y[], r[], u[]) with None gaps.

    The grid is padded 1 row/minute, so index == minutes since t0.
    """
    y, r, u = [], [], []
    t0 = None
    with open(csv_path, 'r', encoding='utf-8-sig') as fh:
        fh.readline()
        for line in fh:
            line = line.rstrip('\r\n')
            parts = line.split(',')
            if t0 is None and parts[0]:
                t0 = datetime.fromisoformat(parts[0])
            def f(i):
                try:
                    return float(parts[i]) if parts[i] else None
                except (ValueError, IndexError):
                    return None
            y.append(f(1)); r.append(f(2)); u.append(f(3))
    return t0, y, r, u


def _err_summary(errs):
    if not errs:
        return None
    abs_errs = [abs(e) for e in errs]
    return {
        'n': len(errs),
        'mean_abs_err_k': round(sum(abs_errs) / len(abs_errs), 2),
        'max_abs_err_k': round(max(abs_errs), 2),
        'mean_signed_err_k': round(sum(errs) / len(errs), 2),
        'pct_within_1k': round(100 * sum(1 for e in abs_errs if e <= 1.0) / len(abs_errs), 1),
    }


def tracking_stats(t0, y, r, winter_only=True):
    """y-vs-r error where both present (winter months by default).

    Split into comfort (setpoint high) vs setback (setpoint low) using the
    midpoint of the setpoint's 10th/90th percentile -- during setbacks a slow
    zone can only cool passively, so its 'error' is physics, not control.
    """
    pairs = []
    for i in range(len(y)):
        if y[i] is None or r[i] is None:
            continue
        if winter_only:
            month = (t0 + timedelta(minutes=i)).month
            if month not in WINTER_MONTHS:
                continue
        pairs.append((r[i], y[i] - r[i]))
    if not pairs:
        return None
    rs = sorted(p[0] for p in pairs)
    mid = (rs[len(rs) // 10] + rs[(len(rs) * 9) // 10]) / 2
    out = _err_summary([e for _, e in pairs])
    out['comfort'] = _err_summary([e for rv, e in pairs if rv >= mid])
    out['setback'] = _err_summary([e for rv, e in pairs if rv < mid])
    return out


def mine_rise_events(y, u, on_pct=50, off_pct=5, max_window_min=360):
    """Heater-ON steps: u jumps low->high and stays; measure the T rise.

    Returns list of {rise_k, tau63_min, gain_k_per_duty, slope_first_30_k_per_h}.
    Closed-loop caveat: the plateau is where the CONTROLLER stops it, so
    gain is a lower bound on open-loop plant gain.
    """
    events = []
    i, n = 0, len(u)
    while i < n - 1:
        ui, uj = u[i], u[i + 1]
        if not (ui is not None and uj is not None and ui <= off_pct and uj >= on_pct):
            i += 1
            continue
        # window: from the jump until u falls below 20% (2 consecutive) or max
        t_start = next((y[k] for k in range(i, max(0, i - 15), -1)
                        if y[k] is not None), None)
        samples, u_sum, u_n, low = [], 0.0, 0, 0
        j = i + 1
        while j < n and j - i <= max_window_min:
            if u[j] is not None:
                u_sum += u[j]; u_n += 1
                low = low + 1 if u[j] < 20 else 0
                if low >= 2:
                    break
            if y[j] is not None:
                samples.append((j - i, y[j]))
            j += 1
        i = j
        if t_start is None or len(samples) < 30 or samples[-1][0] < 60:
            continue
        tail = [t for off, t in samples if off >= samples[-1][0] - 30]
        plateau = sum(tail) / len(tail)
        rise = plateau - t_start
        if rise < 0.5:
            continue
        target = t_start + 0.632 * rise
        tau63 = next((off for off, t in samples if t >= target), None)
        first = [(off, t) for off, t in samples if off <= 30]
        slope = None
        if len(first) >= 5:
            slope = (first[-1][1] - first[0][1]) / max(first[-1][0] - first[0][0], 1) * 60
        mean_u = u_sum / u_n if u_n else None
        events.append({
            'rise_k': round(rise, 2),
            'tau63_min': tau63,
            'gain_k_per_duty': round(rise / (mean_u / 100), 2) if mean_u else None,
            'slope_first_30_k_per_h': round(slope, 2) if slope is not None else None,
        })
    return events


def u_behaviour(u):
    """Saturation / oscillation / modulation stats for the control signal."""
    present = [v for v in u if v is not None]
    if not present:
        return None
    at0 = sum(1 for v in present if v <= 0.5)
    at100 = sum(1 for v in present if v >= 99.5)
    mid = len(present) - at0 - at100
    # on/off transitions (crossings between <10 and >90)
    trans = 0
    state = None
    for v in present:
        s = 'off' if v < 10 else ('on' if v > 90 else None)
        if s and state and s != state:
            trans += 1
        if s:
            state = s
    days = len(u) / 1440
    deltas = [abs(b - a) for a, b in zip(present, present[1:]) if a != b]
    return {
        'pct_at_0': round(100 * at0 / len(present), 1),
        'pct_at_100': round(100 * at100 / len(present), 1),
        'pct_between': round(100 * mid / len(present), 1),
        'distinct_values': len({round(v, 1) for v in present}),
        'onoff_transitions_per_day': round(trans / days, 2) if days else None,
        'mean_step_when_changing': round(sum(deltas) / len(deltas), 2) if deltas else 0.0,
    }


def _quart(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return {'n': len(vals), 'median': round(statistics.median(vals), 1)}


def load_stored_facts(runs_dir):
    """(building, zone) -> stored regime / heatingType / tauMedianMin."""
    facts = {}
    def merge(path, fn):
        p = Path(runs_dir) / path
        if p.exists():
            for row in read_jsonl(p):
                facts.setdefault((row['building'], row['zone']), {}).update(fn(row))
    merge('regimes.jsonl', lambda r: {'regime': r.get('regime')})
    merge('heating_types.jsonl',
          lambda r: {'heatingType': r.get('verdict'), 'confidence': r.get('confidence')})
    merge('step_summary.jsonl',
          lambda r: {'tauMedianMin': (r.get('minutes_to_1k') or {}).get('median')})
    return facts


def plot_zone(zone, t0, y, r, u, week_start, out_png):
    """Two-panel week plot: r+y on top, u below."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    # Normalize week_start timezone to match t0 (COLLECTiEF=aware, Skøyen=naive)
    ws = week_start.replace(tzinfo=None) if t0.tzinfo is None else week_start
    i0 = int((ws - t0).total_seconds() // 60)
    i1 = i0 + 7 * 1440
    i0 = max(i0, 0); i1 = min(i1, len(y))
    ts = [t0 + timedelta(minutes=i) for i in range(i0, i1)]
    seg = lambda a: [a[i] for i in range(i0, i1)]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 6), sharex=True,
                                   gridspec_kw={'height_ratios': [2, 1]})
    ax1.plot(ts, seg(r), color='tab:red', lw=1.0, label='r  setpoint (T_Setvalue)')
    ax1.plot(ts, seg(y), color='tab:blue', lw=0.8, label='y  zone temp (T_Actualvalue)')
    ax1.set_ylabel('deg C')
    ax1.legend(loc='upper right', fontsize=8)
    ax1.set_title(zone)
    ax2.plot(ts, seg(u), color='tab:green', lw=0.7, label='u  gain (T_Gain)')
    ax2.set_ylabel('%')
    ax2.set_ylim(-5, 105)
    ax2.legend(loc='upper right', fontsize=8)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(out_png, dpi=110)
    plt.close(fig)


def probe_zone(building, zone, root, stored):
    csv_path = Path(root) / 'Buildings' / building / 'Thermal zone' / f'{zone}.csv'
    t0, y, r, u = load_series(csv_path)
    rises = mine_rise_events(y, u)
    return {
        'building': building,
        'zone': zone,
        'stored': stored.get((building, zone), {}),
        'tracking_winter': tracking_stats(t0, y, r),
        'rise_events': len(rises),
        'rise_k': _quart([e['rise_k'] for e in rises]),
        'tau63_rise_min': _quart([e['tau63_min'] for e in rises]),
        'gain_k_per_duty': _quart([e['gain_k_per_duty'] for e in rises]),
        'slope_first_30_k_per_h': _quart([e['slope_first_30_k_per_h'] for e in rises]),
        'u': u_behaviour(u),
        '_series': (t0, y, r, u),
    }


def render_report(results, out_dir, plotted):
    lines = ['# r/y/u control-loop probe', '',
             'r = T_Setvalue, y = T_Actualvalue, u = T_Gain (all from the zone CSVs).',
             'Winter = Oct-Mar. Rise gain is a closed-loop LOWER bound on plant gain.', '']
    for res in results:
        s = res['stored']
        lines += [f"## {res['building']} / {res['zone']}",
                  f"stored: heatingType={s.get('heatingType')} regime={s.get('regime')} "
                  f"tauMedianMin={s.get('tauMedianMin')}", '']
        tw = res['tracking_winter']
        if tw:
            lines.append(
                f"- tracking (winter, n={tw['n']}): mean|e|={tw['mean_abs_err_k']}K, "
                f"max|e|={tw['max_abs_err_k']}K, offset={tw['mean_signed_err_k']}K, "
                f"within 1K {tw['pct_within_1k']}% of the time")
            for mode in ('comfort', 'setback'):
                m = tw.get(mode)
                if m:
                    lines.append(
                        f"  - {mode}: mean|e|={m['mean_abs_err_k']}K, "
                        f"offset={m['mean_signed_err_k']}K, within 1K {m['pct_within_1k']}%")
        lines.append(
            f"- rise response ({res['rise_events']} heater-ON events): "
            f"tau63={res['tau63_rise_min']}, rise={res['rise_k']}, "
            f"gain={res['gain_k_per_duty']} K/full-duty, "
            f"first-30min slope={res['slope_first_30_k_per_h']} K/h")
        ub = res['u']
        if ub:
            lines.append(
                f"- u: {ub['pct_at_0']}% at 0, {ub['pct_at_100']}% at 100, "
                f"{ub['pct_between']}% in between; {ub['distinct_values']} distinct values; "
                f"{ub['onoff_transitions_per_day']} on/off transitions/day; "
                f"mean step {ub['mean_step_when_changing']}")
        if res['zone'] in plotted:
            lines.append(f"\n![{res['zone']}]({res['zone']}.png)")
        lines.append('')
    out = Path(out_dir) / 'ryu_report.md'
    out.write_text('\n'.join(lines), encoding='utf-8')
    return out


def _demo():
    """Self-check on synthetic data: known step + known tracking error."""
    # 300 min: setpoint 20, temp 19.5 (offset -0.5), heater ON at min 100
    n = 300
    r = [20.0] * n
    y = [19.5] * n
    u = [0.0] * 100 + [100.0] * 150 + [0.0] * 50
    # exponential-ish rise of 2K after heater-on, tau ~ 40 min
    import math
    for i in range(100, 250):
        y[i] = 19.5 + 2.0 * (1 - math.exp(-(i - 100) / 40))
    t0 = datetime(2023, 1, 1)
    tw = tracking_stats(t0, y, r)
    assert tw and abs(tw['mean_signed_err_k']) < 1.0, tw
    ev = mine_rise_events(y, u)
    assert len(ev) == 1, ev
    assert 25 <= ev[0]['tau63_min'] <= 60, ev
    ub = u_behaviour(u)
    assert ub['pct_between'] == 0.0 and ub['onoff_transitions_per_day'] is not None
    print('demo ok')


def main(argv=None):
    configure_stdout_utf8()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', default=str(DEFAULT_ROOT))
    ap.add_argument('--runs-dir', default=str(DEFAULT_RUNS))
    ap.add_argument('--out-dir', default=str(DEFAULT_OUT))
    ap.add_argument('--zones', help='comma list of BUILDING:ZONE pairs')
    ap.add_argument('--plot', help='comma list of zones to plot (default: all probed)')
    ap.add_argument('--week', default='2023-01-09', help='week start (YYYY-MM-DD) for plots')
    ap.add_argument('--demo', action='store_true')
    args = ap.parse_args(argv)

    if args.demo:
        _demo()
        return 0
    if not args.zones:
        ap.error('give --zones B05:B05-MA-A-2-35,... (or --demo)')

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stored = load_stored_facts(args.runs_dir)
    pairs = [z.split(':') for z in args.zones.split(',')]
    plotted = set(args.plot.split(',')) if args.plot else {z for _, z in pairs}
    week = datetime.fromisoformat(args.week + ' 00:00:00+00:00')

    results = []
    for building, zone in pairs:
        res = probe_zone(building, zone, args.root, stored)
        t0, y, r, u = res.pop('_series')
        if zone in plotted:
            plot_zone(zone, t0, y, r, u, week, out_dir / f'{zone}.png')
        results.append(res)
        print(f'{zone}: {res["rise_events"]} rise events, '
              f'tracking={res["tracking_winter"]}', flush=True)

    report = render_report(results, out_dir, plotted)
    (out_dir / 'ryu_results.jsonl').write_text(
        '\n'.join(json.dumps(r, ensure_ascii=False) for r in results) + '\n',
        encoding='utf-8')
    print(f'report -> {report}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
