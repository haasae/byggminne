"""Validate every example instance against the decoded-label schema.

Run from the repo root:  python src/validate/validate_examples.py
"""
import json
import sys
from pathlib import Path

try:
    from jsonschema import Draft202012Validator
except ImportError:
    sys.exit("Missing dependency. Run: pip install -r requirements.txt")

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "schema" / "decoded_label.schema.json"
EXAMPLES_DIR = ROOT / "examples"


def main() -> int:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)

    failures = 0
    for path in sorted(EXAMPLES_DIR.glob("*.json")):
        instance = json.loads(path.read_text(encoding="utf-8"))
        errors = sorted(validator.iter_errors(instance), key=lambda e: e.path)
        if errors:
            failures += 1
            print(f"[FAIL] {path.name}")
            for err in errors:
                loc = "/".join(str(p) for p in err.path) or "(root)"
                print(f"        {loc}: {err.message}")
        else:
            print(f"[ OK ] {path.name}")

    print("-" * 40)
    print(f"{'All examples valid.' if not failures else f'{failures} file(s) failed.'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
