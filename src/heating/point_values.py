"""Fetch actual time-series values for a zone's point, graph-driven.

Asks Neo4j for the zone's Point pointer (file + column), then streams that
CSV and prints the values -- the graph finds it, this tool reads it.

    python -m src.heating.point_values B03-MA-S-1-22 y --from 2023-01-09 --to 2023-01-10
    python -m src.heating.point_values B03-MA-S-1-22 setpoint --stats
    python -m src.heating.point_values --demo

Signals: r|setpoint, y|sensor|temp, u|actuator|gain.
Needs NEO4J_PASSWORD (env or .env) for the graph lookup; --file/--column
skips the graph entirely (offline mode).
"""
import argparse
import sys
from pathlib import Path

from src.common.io_utils import configure_stdout_utf8

DEFAULT_ROOT = Path('knowledge_base') / 'incoming'

_SIGNAL_ALIASES = {
    'r': 'setpoint', 'setpoint': 'setpoint',
    'y': 'sensor', 'sensor': 'sensor', 'temp': 'sensor',
    'u': 'actuator', 'actuator': 'actuator', 'gain': 'actuator',
}


def lookup_pointer(zone, role):
    """Query Neo4j: zone + role -> (file, column). One MATCH, nothing more."""
    from neo4j import GraphDatabase
    from src.heating.neo4j_import import URI, USER, DATABASE, _load_password

    driver = GraphDatabase.driver(URI, auth=(USER, _load_password()))
    try:
        with driver.session(database=DATABASE) as session:
            rec = session.run(
                "MATCH (z:Zone {id: $zone})-[:HAS_POINT]->(p {role: $role}) "
                "RETURN p.file AS file, p.column AS column",
                zone=zone, role=role).single()
            if rec is None:
                sys.exit(f'ERROR: no {role} point for zone {zone} in the graph')
            return rec['file'], rec['column']
    finally:
        driver.close()


def stream_values(csv_path, column, ts_from=None, ts_to=None):
    """Yield (timestamp, value) for non-empty rows in the range.

    ISO timestamps compare correctly as strings, so range filtering is
    plain prefix comparison -- no datetime parsing per row.
    """
    with open(csv_path, 'r', encoding='utf-8-sig') as fh:
        header = fh.readline().rstrip('\r\n').split(',')
        try:
            col = header.index(column)
        except ValueError:
            sys.exit(f'ERROR: column {column!r} not in {csv_path} (has {header})')
        for line in fh:
            parts = line.rstrip('\r\n').split(',')
            ts = parts[0]
            if ts_from and ts < ts_from:
                continue
            if ts_to and ts[:len(ts_to)] > ts_to:
                break
            if col < len(parts) and parts[col]:
                yield ts, float(parts[col])


def print_stats(rows):
    n, total, lo, hi, first, last = 0, 0.0, None, None, None, None
    for ts, v in rows:
        n += 1
        total += v
        lo = v if lo is None or v < lo else lo
        hi = v if hi is None or v > hi else hi
        first = first or ts
        last = ts
    if n == 0:
        print('no values in range')
        return
    print(f'n={n}  mean={total / n:.2f}  min={lo}  max={hi}')
    print(f'range: {first} .. {last}')


def _demo():
    import tempfile, os
    csv = ('Timestamp,T_Actualvalue,T_Setvalue,T_Gain\n'
           '2023-01-01 00:00:00+00:00,20.5,21,100\n'
           '2023-01-01 00:01:00+00:00,,,\n'
           '2023-01-01 00:02:00+00:00,20.7,21,50\n'
           '2023-01-02 00:00:00+00:00,19.0,19,0\n')
    p = os.path.join(tempfile.mkdtemp(), 'z.csv')
    with open(p, 'w', encoding='utf-8') as fh:
        fh.write(csv)
    rows = list(stream_values(p, 'T_Actualvalue'))
    assert len(rows) == 3, rows
    rows = list(stream_values(p, 'T_Gain', ts_from='2023-01-01', ts_to='2023-01-01'))
    assert [v for _, v in rows] == [100.0, 50.0], rows
    print('demo ok')


def main(argv=None):
    configure_stdout_utf8()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('zone', nargs='?', help='zone id, e.g. B03-MA-S-1-22')
    ap.add_argument('signal', nargs='?', help='r|setpoint, y|sensor, u|actuator')
    ap.add_argument('--from', dest='ts_from', help='YYYY-MM-DD (inclusive)')
    ap.add_argument('--to', dest='ts_to', help='YYYY-MM-DD (inclusive)')
    ap.add_argument('--stats', action='store_true', help='summary instead of rows')
    ap.add_argument('--root', default=str(DEFAULT_ROOT), help='dataset root')
    ap.add_argument('--file', help='CSV path relative to root (skip graph lookup)')
    ap.add_argument('--column', help='column name (skip graph lookup)')
    ap.add_argument('--demo', action='store_true')
    args = ap.parse_args(argv)

    if args.demo:
        _demo()
        return 0
    if not args.zone or not args.signal:
        ap.error('give ZONE and SIGNAL (or --demo)')
    role = _SIGNAL_ALIASES.get(args.signal.lower())
    if role is None:
        ap.error(f'unknown signal {args.signal!r} (use r/y/u)')

    if args.file and args.column:
        rel, column = args.file, args.column
    else:
        rel, column = lookup_pointer(args.zone, role)
    csv_path = Path(args.root) / rel
    if not csv_path.exists():
        sys.exit(f'ERROR: {csv_path} not found (is --root correct?)')

    rows = stream_values(csv_path, column, args.ts_from, args.ts_to)
    if args.stats:
        print_stats(rows)
    else:
        for ts, v in rows:
            print(f'{ts},{v}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
