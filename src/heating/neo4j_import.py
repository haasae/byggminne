"""Import runs/heating/neo4j_import.cypher into a local Neo4j instance.

Reads NEO4J_PASSWORD from the environment (or a .env file if python-dotenv is
available).  Runs constraints first (one per tx), then batches the remaining
statements at ~500 per transaction.

Usage:
    NEO4J_PASSWORD=secret python -m src.heating.neo4j_import
    python -m src.heating.neo4j_import --cypher runs/heating/neo4j_import.cypher
"""
import argparse
import os
import sys
import time
from pathlib import Path

from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError

RETRIES = 5  # constraint creation makes the db briefly unavailable

DEFAULT_CYPHER = Path('runs') / 'heating' / 'neo4j_import.cypher'
URI = 'bolt://127.0.0.1:7687'
USER = 'neo4j'
DATABASE = 'neo4j'
BATCH = 500


def _load_password():
    pw = os.environ.get('NEO4J_PASSWORD')
    if not pw:
        # Optional: load from .env without requiring python-dotenv
        env_file = Path('.env')
        if env_file.exists():
            for line in env_file.read_text(encoding='utf-8').splitlines():
                if line.startswith('NEO4J_PASSWORD='):
                    pw = line.split('=', 1)[1].strip().strip('"').strip("'")
                    break
    if not pw:
        sys.exit('ERROR: set NEO4J_PASSWORD in environment or .env file')
    return pw


def _parse_statements(cypher_path):
    """One statement per line; strip trailing ; and skip comments/blanks."""
    stmts = []
    for line in Path(cypher_path).read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('//'):
            continue
        stmts.append(line.rstrip(';'))
    return stmts


def _run(driver, stmts):
    constraints = [s for s in stmts if s.upper().startswith('CREATE CONSTRAINT')]
    rest = [s for s in stmts if not s.upper().startswith('CREATE CONSTRAINT')]

    with driver.session(database=DATABASE) as session:
        print(f'Running {len(constraints)} constraint statements...')
        for stmt in constraints:
            try:
                session.run(stmt)
            except Exception as exc:
                print(f'\nFAILED statement:\n{stmt}\n\nException: {exc}')
                raise

        print(f'Batching {len(rest)} data statements in groups of {BATCH}...')
        total = 0
        for i in range(0, len(rest), BATCH):
            batch = rest[i:i + BATCH]
            for attempt in range(RETRIES):
                try:
                    with session.begin_transaction() as tx:
                        for stmt in batch:
                            tx.run(stmt)
                        tx.commit()
                    break
                except Neo4jError as exc:
                    if attempt < RETRIES - 1 and exc.is_retryable():
                        wait = 2 * (attempt + 1)
                        print(f'\n  transient error ({exc.code}); '
                              f'retrying in {wait}s...')
                        time.sleep(wait)
                        continue
                    culprit = batch[0] if batch else '(unknown)'
                    print(f'\nFAILED in batch {i//BATCH + 1}.\nFirst stmt in batch:\n{culprit}\n\nException: {exc}')
                    raise
                except Exception as exc:
                    culprit = batch[0] if batch else '(unknown)'
                    print(f'\nFAILED in batch {i//BATCH + 1}.\nFirst stmt in batch:\n{culprit}\n\nException: {exc}')
                    raise
            total += len(batch)
            print(f'  committed {total}/{len(rest)}', end='\r')
        print()


def _verify(driver):
    print('\n── Verification ─────────────────────────────────────────')
    with driver.session(database=DATABASE) as session:
        result = session.run('MATCH (n) RETURN count(n) AS total')
        print(f'Total nodes : {result.single()["total"]}')

        for label in ('Site', 'Building', 'SubBuilding', 'Level', 'Zone',
                      'Room', 'System', 'Meter', 'Point'):
            result = session.run(f'MATCH (n:{label}) RETURN count(n) AS c')
            print(f'  :{label:<14} {result.single()["c"]}')

        result = session.run('MATCH ()-[r]->() RETURN count(r) AS total')
        print(f'Total rels  : {result.single()["total"]}')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--cypher', default=str(DEFAULT_CYPHER))
    args = ap.parse_args(argv)

    password = _load_password()
    stmts = _parse_statements(args.cypher)
    print(f'Parsed {len(stmts)} statements from {args.cypher}')

    driver = GraphDatabase.driver(URI, auth=(USER, password))
    try:
        driver.verify_connectivity()
        print(f'Connected to {URI}')
        _run(driver, stmts)
        _verify(driver)
    finally:
        driver.close()


if __name__ == '__main__':
    main()
