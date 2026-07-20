"""Layer 1 helper: accumulate a control-number -> area lookup table in the KB.

A control number (segment 2a of a BACnet/SD label, e.g. `20053401`) identifies a
building scoped to a physical area. Per knowledge_base/bacnet_sd_label_grammar.md,
we must NOT hardcode these into CLAUDE.md; instead we derive the mapping
empirically by scanning the available data files and accumulating what we observe
into knowledge_base/control_number_area_map.md, which then becomes part of the
decode context pack so the decoder can resolve a control number to its area.

How the mapping is read (cheap: file names only, never the multi-GB contents):
- Area = the immediate parent folder of each data file
  (data/raw/tasen/... -> area `tasen`).
- The control number is a standalone run of 8 digits in the file name, which for
  this dataset encodes `<controlnumber>-<Area>-<OU...>`
  (e.g. `20053401-Tasen-OU001 AV punkter 2025.csv`).

How the decoder uses the output:
- The map is included verbatim in the decode context pack
  (src/decode/context_pack.py), so the LLM decode path sees it as citable reference.
- The deterministic rules engine reads it at decode time via
  kb_lookup.control_number_areas(): it pulls the control number out of a label's
  segment 2a, keeps it as location.building, and -- when this map has a row for
  it -- appends the area name with a citation, e.g.
      "...:20053401-OU001/..." -> location.building 20053401, area tasen
      (cited: control_number_area_map.md row '20053401')
- A control number absent from this map still becomes the building id; only the
  friendly area name is omitted -- never invented.

Usage (regenerate after adding data; Tasen is just an example -- any file name
with an 8-digit control number works):

    # Scan the default tree (data/raw) -> the default KB map
    python -m src.extract.control_number_map

    # Explicit data root and output path
    python -m src.extract.control_number_map --data-dir data/raw \
        -o knowledge_base/control_number_area_map.md

    --data-dir   root of the raw data tree to scan (default: data/raw)
    -o           output Markdown file (default: knowledge_base/control_number_area_map.md)
    (-m is Python's own flag for running a module as a script, not a flag of this tool)

A control number seen under two different areas is flagged as a conflict rather
than silently overwritten (the CLI prints a warning).
"""

import argparse
import re
from pathlib import Path

from src.common.io_utils import configure_stdout_utf8, repo_root

# A control number is a standalone run of 8 digits in the file name.
_CONTROL_NUMBER = re.compile(r"(?<!\d)\d{8}(?!\d)")

DEFAULT_OUTPUT = "knowledge_base/control_number_area_map.md"


def control_numbers_in_name(name):
    """Return the 8-digit control numbers found in a file name (order-preserving)."""

    return _CONTROL_NUMBER.findall(name)


def scan(data_dir):
    """Walk the data tree, accumulate a control-number -> area map, and detect conflicts.

    Args:
        data_dir (str or Path): Root of the raw data tree to scan.

    Returns:
        tuple: A tuple containing:
            - mapping (dict): A dictionary mapping control numbers to their corresponding area and files.
            - conflicts (dict): A dictionary of control numbers that are seen under more than one area.
            - n_files (int): The total number of files scanned.
            - n_without_number (int): The number of files that did not contain a control number in their name.
    """

    data_dir = Path(data_dir)
    mapping = {}
    conflicts = {}
    n_files = 0
    n_without_number = 0

    for path in sorted(data_dir.rglob("*.csv")): # recursively find all CSV files under data_dir
        # sorted() ensures deterministic output, so the same input tree always produces the same map file.
        n_files += 1
        area = path.parent.name
        numbers = control_numbers_in_name(path.name)
        if not numbers:
            n_without_number += 1
            continue
        for number in numbers:
            # - If we've never seen this control number, a fresh {"area": area, "files": set()} is stored under it, and entry points to that.
            # - If we have seen it before, setdefault hands back the entry that's already in mapping, and the fresh {"area": area, ...} we passed is built and immediately thrown away — unused.
            entry = mapping.setdefault(number, {"area": area, "files": set()})
            entry["files"].add(path.name)
            if entry["area"] != area:
                conflicts.setdefault(number, set()).update({entry["area"], area})

    # Freeze the file sets into sorted lists for deterministic output.
    for entry in mapping.values():
        entry["files"] = sorted(entry["files"])
    conflicts = {k: sorted(v) for k, v in conflicts.items()}
    return mapping, conflicts, n_files, n_without_number


def render_markdown(mapping, conflicts, n_files, n_without_number):
    """Render the control-number -> area map as a Markdown table.

    List of strings is built up in `L` and joined with newlines at the end. First a header and summary, then the table, then any conflicts. 
    The table has three columns: control number, area, and the files in which that control number was seen. 
    If there are any conflicts (same control number under multiple areas), they are listed after the table.
    """
    L = [
        "# Control number -> area map (auto-generated)",
        "",
        "Auto-generated by `python -m src.extract.control_number_map` from the data",
        "files under `data/raw/`. **Do not edit by hand -- regenerate after adding",
        "data.** Area is each data file's parent folder; control numbers are read from",
        "the file names (`<controlnumber>-<Area>-<OU...>`). This file is part of the",
        "decode context pack: use it to resolve a label's control number (segment 2a,",
        "between `:` and `/`) to its area. See `bacnet_sd_label_grammar.md`.",
        "",
        f"Scanned {n_files} data file(s); {n_without_number} had no control number in the name.",
        "",
    ]
    if not mapping:
        L.append("_No control numbers observed yet (no matching data files present)._")
        L.append("")
        return "\n".join(L)

    L.append("| Control number | Area | Seen in files |")
    L.append("|---|---|---|")
    for number in sorted(mapping):
        entry = mapping[number]
        files = "; ".join(entry["files"])
        L.append(f"| {number} | {entry['area']} | {files} |")
    L.append("")

    if conflicts:
        L.append("## Conflicts (same control number, multiple areas)")
        L.append("")
        L.append("Investigate these -- a control number should map to a single area.")
        L.append("")
        for number, areas in sorted(conflicts.items()):
            L.append(f"- `{number}`: {', '.join(areas)}")
        L.append("")

    return "\n".join(L)


def main() -> int:
    """Parse the command line → figure out the paths → call scan() and render_markdown() → write the file → report.

    main() resolves --data-dir and -o (defaulting to <repo>/data/raw and <repo>/knowledge_base/control_number_area_map.md), 
    writes the map file, prints a one-line summary, and warns if any control number was seen under more than one area.

    Returns:
        int: Exit code (0 for success).
    """

    configure_stdout_utf8()
    ap = argparse.ArgumentParser(
        description="Accumulate a control-number -> area lookup table into the knowledge base."
    )
    ap.add_argument("--data-dir", default=None,
                    help="root of the raw data tree (default: <repo>/data/raw)")
    ap.add_argument("-o", "--output", default=None,
                    help=f"output markdown file (default: <repo>/{DEFAULT_OUTPUT})")
    args = ap.parse_args()

    root = repo_root()
    data_dir = Path(args.data_dir) if args.data_dir else root / "data" / "raw"
    output = Path(args.output) if args.output else root / DEFAULT_OUTPUT

    mapping, conflicts, n_files, n_without_number = scan(data_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        render_markdown(mapping, conflicts, n_files, n_without_number),
        encoding="utf-8",
    )
    print(f"{len(mapping)} control number(s) from {n_files} file(s) -> {output}")
    if conflicts:
        print(f"WARNING: {len(conflicts)} control number(s) map to multiple areas.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
