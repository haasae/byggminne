"""Shared I/O helpers.

Everything reads and writes UTF-8 because labels and descriptions are Norwegian
(ae/oe/aa). JSON is dumped with ensure_ascii=False so those characters stay
readable in the files we produce.
"""
import json
import sys
from pathlib import Path


def repo_root() -> Path:
    """Repo root = two levels above this file (src/common/io_utils.py)."""
    return Path(__file__).resolve().parents[2]


def default_schema_path() -> Path:
    return repo_root() / "schema" / "decoded_label.schema.json"


def configure_stdout_utf8() -> None:
    """Avoid UnicodeEncodeError when printing ae/oe/aa on a non-UTF-8 console."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, obj) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_jsonl(path):
    """Read a JSON-Lines file into a list of objects (blank lines skipped)."""
    rows = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                rows.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
    return rows


def write_jsonl(path, rows) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_schema(schema_path=None):
    return read_json(schema_path or default_schema_path())
