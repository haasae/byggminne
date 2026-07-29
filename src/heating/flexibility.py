"""Phase 4c: per-zone flexibility indicators -> human-readable ranking.

Reads from runs/heating/ (not from the graph -- same facts, direct access).
Ranks heating-oriented, non-excluded zones by flexibility potential:
  - Fast electric: can be switched on/off quickly -> demand response
  - Slow mass (floor/hydronic): can be pre-heated -> energy shifting

Emits runs/heating/flexibility_map.md.

    python -m src.heating.flexibility [--runs-dir ...] [-o ...]
"""
import argparse
import sys
from pathlib import Path

from src.common.io_utils import configure_stdout_utf8, read_jsonl

# Verdict display order and short description
_VERDICT_ORDER = [
    ('electric-fast',  'Fast electric -- demand response candidate'),
    ('hydronic-slow',  'Hydronic -- pre-heat candidate'),
    ('floor-slow',     'Floor/high-mass -- pre-heat candidate'),
    ('ambiguous',      'Ambiguous -- insufficient thermal evidence'),
    ('excluded',       'Excluded -- cooling/dual/idle orientation'),
]
_ORDER = {v: i for i, (v, _) in enumerate(_VERDICT_ORDER)}


def _load(runs_dir):
    ht = {(r['building'], r['zone']): r
          for r in read_jsonl(runs_dir / 'heating_types.jsonl')}
    tau = {(r['building'], r['zone']): r
           for r in read_jsonl(runs_dir / 'step_summary.jsonl')
           if r.get('minutes_to_1k')}
    orient = {(r['building'], r['zone']): r
              for r in read_jsonl(runs_dir / 'orientation.jsonl')}
    return ht, tau, orient


def rank_zones(ht, tau, orient):
    rows = []
    for (building, zone), ht_row in sorted(ht.items()):
        verdict = ht_row['verdict']
        tau_row = tau.get((building, zone))
        tau_med = (tau_row['minutes_to_1k']['median']
                   if tau_row and tau_row.get('minutes_to_1k') else None)
        o = orient.get((building, zone), {})
        winter_duty = o.get('winter_duty')
        headroom = round(100.0 - winter_duty, 1) if winter_duty is not None else None
        rows.append({
            'building': building,
            'zone': zone,
            'verdict': verdict,
            'confidence': ht_row['confidence'],
            'tau_med_min': tau_med,
            'winter_duty_pct': winter_duty,
            'headroom_pct': headroom,
            'orientation': o.get('orientation', 'unknown'),
        })
    # Sort: verdict order first, then tau ascending (faster = more flexible)
    rows.sort(key=lambda r: (
        _ORDER.get(r['verdict'], 99),
        r['tau_med_min'] if r['tau_med_min'] is not None else 9999,
        r['zone'],
    ))
    return rows


def render(rows, out_path):
    lines = ['# Flexibility map (Phase 4)', '',
             'Zones ranked by flexibility potential.',
             'Tau = median minutes to cool 1 K (lower = faster response).',
             'Headroom = 100% - winter duty cycle (unused heating capacity).', '']

    for verdict, desc in _VERDICT_ORDER:
        group = [r for r in rows if r['verdict'] == verdict]
        if not group:
            continue
        lines += [f'## {desc} ({len(group)} zones)', '',
                  '| Building | Zone | Tau (min) | Winter duty | Headroom | Confidence |',
                  '|---|---|---|---|---|---|']
        for r in group:
            tau_s = f"{r['tau_med_min']:.0f}" if r['tau_med_min'] is not None else '—'
            duty_s = f"{r['winter_duty_pct']:.1f}%" if r['winter_duty_pct'] is not None else '—'
            head_s = f"{r['headroom_pct']:.1f}%" if r['headroom_pct'] is not None else '—'
            lines.append(
                f"| {r['building']} | {r['zone']} | {tau_s} | {duty_s} | {head_s} "
                f"| {r['confidence']:.2f} |"
            )
        lines.append('')

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text('\n'.join(lines), encoding='utf-8')
    return len(rows)


def main(argv=None):
    configure_stdout_utf8()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--runs-dir', default=str(Path('runs') / 'heating'))
    ap.add_argument('-o', '--out',
                    default=str(Path('runs') / 'heating' / 'flexibility_map.md'))
    args = ap.parse_args(argv)

    runs_dir = Path(args.runs_dir)
    ht, tau, orient = _load(runs_dir)
    rows = rank_zones(ht, tau, orient)
    n = render(rows, Path(args.out))
    print(f'{n} zones -> {args.out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
