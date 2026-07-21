"""Validate every example instance against the decoded-label schema.

Run from the repo root:  python -m src.validate.validate_examples
Thin wrapper over src.validate.schema_validator (restores the original script).
"""
from src.common.io_utils import configure_stdout_utf8, repo_root
from src.validate.schema_validator import build_validator, validate_file


def main() -> int:
    configure_stdout_utf8()
    validator = build_validator()
    examples_dir = repo_root() / "examples"

    failures = 0
    for path in sorted(examples_dir.glob("*.json")):
        errors = validate_file(path, validator)
        if errors:
            failures += 1
            print(f"[FAIL] {path.name}")
            for loc, msg in errors:
                print(f"        {loc}: {msg}")
        else:
            print(f"[ OK ] {path.name}")

    print("-" * 40)
    print("All examples valid." if not failures else f"{failures} file(s) failed.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
