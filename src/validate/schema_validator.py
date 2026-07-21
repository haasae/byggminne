"""Validate decoded-label instances against the JSON schema.

Generalizes the original src/validate/validate_examples.py so both the decoder
(reject invalid model output) and the harness (schema-validity rate) reuse one
implementation. Library + a small CLI for validating a single file or a JSONL.
"""
import argparse
import sys

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - exercised only without the dependency
    sys.exit("Missing dependency. Run: pip install -r requirements.txt")

from src.common.io_utils import (
    configure_stdout_utf8,
    load_schema,
    read_json,
    read_jsonl,
)


def build_validator(schema_path=None) -> Draft202012Validator:
    return Draft202012Validator(load_schema(schema_path))


def validate_instance(instance, validator):
    """Return a list of (location, message) tuples; empty list means valid."""
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
    out = []
    for err in errors:
        loc = "/".join(str(p) for p in err.path) or "(root)"
        out.append((loc, err.message))
    return out


def validate_file(path, validator):
    return validate_instance(read_json(path), validator)


def _main() -> int:
    configure_stdout_utf8()
    ap = argparse.ArgumentParser(description="Validate decoded labels against the schema.")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--file", help="single JSON instance to validate")
    group.add_argument("--jsonl", help="JSONL file; validate every line")
    ap.add_argument("--schema", help="schema path (defaults to schema/decoded_label.schema.json)")
    args = ap.parse_args()

    validator = build_validator(args.schema)

    if args.file:
        errors = validate_file(args.file, validator)
        if errors:
            for loc, msg in errors:
                print(f"{loc}: {msg}")
            return 1
        print("valid")
        return 0

    failures = 0
    for i, instance in enumerate(read_jsonl(args.jsonl)):
        key = instance.get("raw_label", f"row {i}")
        errors = validate_instance(instance, validator)
        if errors:
            failures += 1
            print(f"[FAIL] {key}")
            for loc, msg in errors:
                print(f"        {loc}: {msg}")
        else:
            print(f"[ OK ] {key}")
    print("-" * 40)
    print("All valid." if not failures else f"{failures} row(s) failed.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_main())
