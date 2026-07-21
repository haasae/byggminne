"""Extract tables from a PDF as Markdown.

Works best with PDFs that have drawn grids around the tables (pymupdf's
find_tables detects cells from the grid). Requires `pip install pymupdf`.

Usage:
    python src/PDF-parser/parse.py docs/Komponentkodeliste.pdf -o out/tables.md
"""
import argparse
from pathlib import Path

import pymupdf


def main() -> int:
    ap = argparse.ArgumentParser(description="Extract PDF tables to Markdown.")
    ap.add_argument("pdf", help="input PDF file")
    ap.add_argument("-o", "--output", required=True, help="output Markdown file")
    args = ap.parse_args()

    doc = pymupdf.open(args.pdf)
    chunks = []
    for page in doc:
        for t in page.find_tables().tables:  # detects cells from the drawn grid
            chunks.append(t.to_markdown())

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n\n".join(chunks), encoding="utf-8")
    print(f"Extracted {len(chunks)} tables -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
