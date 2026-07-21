#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_table.py - verify a Markdown table (converted from a PDF) against the PDF.

These Statsbygg / NS-3451 PDFs stagger their table cells *vertically*: the text
of a wrapped Veiledning line does not sit on the same baseline as its code, so
naive text extraction (pdftotext, most PDF->Markdown converters) scrambles which
text belongs to which row. This tool reconstructs the true table geometrically:

  1. ROW detection  - the horizontal rule lines drawn on the page define the row
     bands. We read them from the vector drawings and cluster nearby lines.
  2. COLUMN assignment - each *word* (with its own x-coordinate) is bucketed into
     column 1/2/3 by comparing its left edge x0 against two x-thresholds. Using
     words (not spans) correctly splits rows where the Veiledning text and the
     "Systemkode i TFM" comment share one padded text span.
  3. Lines within a cell are regrouped by y and joined with " / ".

The reconstruction is cached to a .txt (human-readable). The Markdown <table>
rows are then parsed and compared cell-by-cell, ignoring whitespace and line
breaks, so only genuine *content* disagreements are emitted.

Column thresholds (C1 < --col2 <= C2 < --col3 <= C3) were measured on
docs/tfm_systemkodeliste.pdf and are the defaults: col2=225, col3=438. For a
different PDF, re-measure (e.g. histogram word x0 values) and pass new values.

OVERFLOW: a tall cell can overflow its row's rule line, so its last wrapped line
lands in the *next* band. Such a difference is tagged "[overflow-suspect]" (the
md content straddles a reconstructed row boundary) and the adjacent truth cells
are shown so it can be judged against the rendered page. NOTE: a real downward
"bleed" also straddles a boundary, so --hide-overflow is heuristic and lossy;
it is OFF by default. Always confirm overflow-suspects visually.

Usage:
    python verify_table.py --pdf docs/tfm_systemkodeliste.pdf \
                           --md  knowledge_base/TFM_systemkodeliste_dir/TFM_systemkodeliste.md
Requires: pymupdf  (pip install pymupdf)
"""

import argparse
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    import fitz  # PyMuPDF
except ImportError:
    sys.exit("verify_table.py needs PyMuPDF. Install it with:  pip install pymupdf")


# --------------------------------------------------------------------------- #
# Geometric reconstruction
# --------------------------------------------------------------------------- #
def cluster(values, tol):
    """Collapse near-equal coordinates into their group means."""
    out = []
    for v in sorted(values):
        if out and v - out[-1][-1] <= tol:
            out[-1].append(v)
        else:
            out.append([v])
    return [sum(g) / len(g) for g in out]


def row_separators(page, row_tol):
    """Y-coordinates of the page's horizontal rule lines (table row borders)."""
    ys = set()
    for d in page.get_drawings():
        for it in d["items"]:
            if it[0] == "l":                       # line segment
                p1, p2 = it[1], it[2]
                if abs(p1.y - p2.y) < 0.6:         # horizontal
                    ys.add(p1.y)
            elif it[0] == "re":                    # rectangle -> its top & bottom
                r = it[1]
                ys.add(r.y0)
                ys.add(r.y1)
    return cluster(ys, row_tol)


def reconstruct_page(page, col2, col3, row_tol, line_tol):
    """Return [(c1, c2, c3), ...] logical rows for one page."""
    seps = row_separators(page, row_tol)
    bands = [(seps[i], seps[i + 1]) for i in range(len(seps) - 1)]
    words = page.get_text("words")  # (x0, y0, x1, y1, word, block, line, wordno)

    rows = []
    for top, bot in bands:
        cells = {0: [], 1: [], 2: []}
        for x0, y0, x1, y1, w, *_ in words:
            cy = (y0 + y1) / 2.0
            if top - 1 <= cy < bot + 1:
                col = 0 if x0 < col2 else (1 if x0 < col3 else 2)
                cells[col].append((y0, x0, w))
        if not any(cells.values()):
            continue

        def join(col):
            items = sorted(cells[col], key=lambda z: (round(z[0] / 2.0), z[1]))
            lines = []
            for y0, _x0, w in items:
                if lines and abs(y0 - lines[-1][0]) < line_tol:
                    lines[-1][1].append(w)
                else:
                    lines.append([y0, [w]])
            return " / ".join(" ".join(parts) for _y, parts in lines)

        rows.append((join(0), join(1), join(2)))
    return rows


def reconstruct_pdf(pdf_path, col2, col3, row_tol, line_tol):
    doc = fitz.open(pdf_path)
    pages = []
    for pno in range(doc.page_count):
        pages.append((pno + 1, reconstruct_page(doc[pno], col2, col3, row_tol, line_tol)))
    doc.close()
    return pages


# --------------------------------------------------------------------------- #
# Cache (human-readable ground truth)
# --------------------------------------------------------------------------- #
def write_cache(path, pages):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        for pno, rows in pages:
            fh.write("===== PAGE %d =====\n" % pno)
            for c1, c2, c3 in rows:
                fh.write("C1: %s\nC2: %s\nC3: %s\n--\n" % (c1, c2, c3))


def read_cache(path):
    """Return ordered list of (c1, c2, c3) from a cache written by write_cache."""
    rows = []
    block = {}
    for line in open(path, encoding="utf-8"):
        line = line.rstrip("\n")
        if line.startswith("====="):
            continue
        if line == "--":
            if block:
                rows.append((block.get("C1", ""), block.get("C2", ""), block.get("C3", "")))
                block = {}
            continue
        for key in ("C1", "C2", "C3"):
            if line.startswith(key + ": "):
                block[key] = line[len(key) + 2:]
    if block:
        rows.append((block.get("C1", ""), block.get("C2", ""), block.get("C3", "")))
    return rows


# --------------------------------------------------------------------------- #
# Markdown parsing + comparison
# --------------------------------------------------------------------------- #
def strip_cell(html):
    """<br/> -> ' / ', drop tags, collapse whitespace."""
    s = html.replace("<br/>", " / ")
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", s).strip()


def squash(s):
    """Whitespace/line-break-insensitive form for content comparison."""
    s = s.replace("<br/>", " ").replace("/", " ")
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", "", s).lower()


def leading_code(text):
    m = re.match(r"(\d+)\b", text)
    return m.group(1) if m else None


def parse_md_rows(md_text):
    """Return ordered list of (code, c1, c2, c3) for every 3-cell data row."""
    out = []
    for tr in re.findall(r"<tr>(.*?)</tr>", md_text, re.S):
        cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, re.S)
        if len(cells) != 3:
            continue
        c1, c2, c3 = (strip_cell(c) for c in cells)
        code = leading_code(c1)
        if code is None:           # header / label rows (no numeric code)
            continue
        out.append((code, c1, c2, c3))
    return out


def index_truth(truth_rows):
    """Map code -> position; codes are unique in these documents."""
    by_code = {}
    for i, (c1, _c2, _c3) in enumerate(truth_rows):
        code = leading_code(c1)
        if code and code not in by_code:
            by_code[code] = i
    return by_code


def spans_boundary(md_val, truth_rows, idx, col):
    """True if md content straddles a reconstructed row boundary at idx (col 1=C2,2=C3).

    Signals a tall-cell overflow OR a real downward bleed -- inspect visually.
    """
    m = squash(md_val)
    if not m:
        return True  # empty md vs non-empty truth is usually a neighbour overflow
    here = squash(truth_rows[idx][col])
    prev = squash(truth_rows[idx - 1][col]) if idx > 0 else ""
    nxt = squash(truth_rows[idx + 1][col]) if idx + 1 < len(truth_rows) else ""
    return m in (here + nxt) or m in (prev + here)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(
        description="Verify a PDF->Markdown table by geometric reconstruction.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--pdf", required=True, help="source PDF")
    ap.add_argument("--md", required=True, help="Markdown file containing <table> rows")
    ap.add_argument("--cache", default=None,
                    help="ground-truth cache path (default: <md>.truth.txt)")
    ap.add_argument("--col2", type=float, default=225.0,
                    help="x-threshold: words with x0 >= this start column 2 (Veiledning)")
    ap.add_argument("--col3", type=float, default=438.0,
                    help="x-threshold: words with x0 >= this start column 3 (TFM kommentarer)")
    ap.add_argument("--row-tol", type=float, default=2.5,
                    help="cluster tolerance (pt) for merging near-duplicate rule lines")
    ap.add_argument("--line-tol", type=float, default=3.5,
                    help="max y-gap (pt) for words counted as the same wrapped line")
    ap.add_argument("--columns", choices=["c2c3", "all"], default="c2c3",
                    help="which columns to diff ('all' also checks the code column)")
    ap.add_argument("--refresh", action="store_true",
                    help="rebuild the cache even if it already exists")
    ap.add_argument("--hide-overflow", action="store_true",
                    help="suppress overflow-suspect rows (heuristic & lossy: may hide real bleeds)")
    args = ap.parse_args()

    cache = args.cache or os.path.splitext(args.md)[0] + ".truth.txt"

    if args.refresh or not os.path.exists(cache):
        pages = reconstruct_pdf(args.pdf, args.col2, args.col3, args.row_tol, args.line_tol)
        write_cache(cache, pages)
        print("[reconstructed %d pages -> %s]" % (len(pages), cache), file=sys.stderr)
    else:
        print("[using cached truth %s  (--refresh to rebuild)]" % cache, file=sys.stderr)

    truth_rows = read_cache(cache)
    by_code = index_truth(truth_rows)
    md_rows = parse_md_rows(open(args.md, encoding="utf-8").read())

    cols = [(1, "C2"), (2, "C3")] if args.columns == "c2c3" else [(0, "C1"), (1, "C2"), (2, "C3")]
    n_diff = n_overflow = 0

    for code, c1, c2, c3 in md_rows:
        md_cells = {0: c1, 1: c2, 2: c3}
        if code not in by_code:
            print("### code %s  (%s)\n    [NO TRUTH ROW for this code]" % (code, c1))
            n_diff += 1
            continue
        idx = by_code[code]
        diffs = []
        for col, name in cols:
            md_val = md_cells[col]
            truth_val = truth_rows[idx][col]
            if squash(md_val) == squash(truth_val):
                continue
            overflow = spans_boundary(md_val, truth_rows, idx, col)
            if overflow and args.hide_overflow:
                continue
            diffs.append((name, col, md_val, truth_val, overflow))

        if not diffs:
            continue
        print("### code %s  (%s)" % (code, c1))
        for name, col, md_val, truth_val, overflow in diffs:
            tag = "  [overflow-suspect: straddles a reconstructed row boundary]" if overflow else ""
            print("  %s MD    : %s" % (name, md_val))
            print("  %s TRUTH : %s%s" % (name, truth_val, tag))
            if overflow:
                n_overflow += 1
                prev = truth_rows[idx - 1][col] if idx > 0 else ""
                nxt = truth_rows[idx + 1][col] if idx + 1 < len(truth_rows) else ""
                print("        truth prev row %s: %s" % (name, prev))
                print("        truth next row %s: %s" % (name, nxt))
            n_diff += 1

    print("\n[%d disagreeing cell(s); %d overflow-suspect -- verify those against the rendered page]"
          % (n_diff, n_overflow), file=sys.stderr)
    sys.exit(1 if n_diff else 0)


if __name__ == "__main__":
    main()
