"""Layer 1 helper: stream (possibly huge) CSVs and return unique labels.

The CSVs have millions of rows, but we expect only a small set of distinct
labels. We stream the files, extract that unique set, and write it to a text
file so the decode step can reuse it instead of decoding the same label
many times over.

Line format (no header): `label,timestamp,value`.
The two LAST comma-separated fields are peeled off the right (timestamp,
value); everything before them is the label -- so the label itself may
contain anything, including commas. The timestamp and value must not
contain commas: semicolon-separated exports and decimal-comma values would
silently corrupt the labels, so `warn_suspicious` flags both patterns.

Usage (Tasen is just an example dataset; any CSV in this format works):

    # All CSVs in a directory -> labels.txt
    python -m src.extract.unique_labels "data/raw/tasen/*.csv" -o labels.txt

    # A single CSV -> labels.tsv, with occurrence counts, sorted descending
    python -m src.extract.unique_labels data/raw/tasen/file.csv -o labels.tsv --with-counts

    -o             output file
    --with-counts  include per-label occurrence counts in the output
    (-m is Python's own flag for running a module as a script, not a flag of this tool)

    .tsv is tab-separated, so it imports cleanly into Excel or other spreadsheets.
"""

import argparse # for command line argument parsing
import glob # utlility to search for files matching a pattern
import re
import sys
from collections import Counter # tool to count unique labels
from pathlib import Path # handles file paths

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

"""
- sys.path.insert(0, ...) inserts this directory path at index 0, which is the front of the list of directories Python searches for modules. 
This allows us to import modules from the src directory.
- __file__ is this file's own path (.../src/extract/unique_labels.py).
- .parents[2] goes up two levels to the root of the project (the parent of src).
"""

from src.common.io_utils import configure_stdout_utf8 # Helps with Norwegian characters

def iter_labels(csv_path):
    """
    Iterates over the labels in a CSV file, strips whitespace, splits two times from the right to remove timestamp and value, and yields the label.

    Args:
        csv_path (str or Path): Path to the CSV file.
    
    Returns:
        str: The label from the first column of the CSV file.

    The CSV files are expected to have the format: label,timestamp,value
    """

    with open(csv_path, "r", encoding="utf-8-sig", newline="") as fh:
        for line in fh:
            line = line.rstrip("\r\n")
            if not line:
                continue
            yield line.rsplit(",", 2)[0]


def collect(paths) -> Counter:
    """
    Loops through CSV files and collects unique labels, counting their occurrences. 
    Uses the iter_labels function to extract labels from each CSV file.

    Args:
        paths (list of str or Path): List of CSV file paths.

    Returns:
        Counter: A Counter object mapping each unique label to its count across all files.
    """

    counter = Counter()
    for path in paths:
        for label in iter_labels(path):
            counter[label] += 1
    return counter


# ISO (2025-01-31) or Norwegian (31.01.2025) date -- a date INSIDE a label is
# the fingerprint of a shifted split (glued 'label,timestamp')
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}|\d{2}\.\d{2}\.\d{4}")


def warn_suspicious(counter):
    """Return warning strings for the two silent-corruption patterns.

    Both traps produce plausible-looking garbage instead of an error, so the
    labels themselves are inspected after extraction:
    - semicolon-separated export: the whole line survives as the "label"
    - decimal comma in the value: the split shifts and the label ends up as
      'name,timestamp' glued together
    """
    labels = list(counter)
    n = len(labels)
    if not n:
        return []
    warnings = []
    if sum(1 for lbl in labels if ";" in lbl) > n / 2:
        warnings.append(
            "WARNING: most labels contain ';' -- the file(s) look semicolon-separated "
            "(Norwegian Excel default). This tool needs comma-separated CSV. "
            "Please re-export with ',' as the delimiter."
        )
    if sum(1 for lbl in labels if "," in lbl and _DATE_RE.search(lbl)) > n / 5:
        warnings.append(
            "WARNING: many labels look like 'name,timestamp' glued together -- the "
            "value column probably uses decimal comma (21,5). Use decimal point (21.5)."
        )
    return warnings


def _resolve(patterns):
    """
    Takes what the user typed on the command line (file paths or glob patterns) and returns a list of Path objects for the matching files.

    Args:
        patterns (list of str): List of file paths or glob patterns.

    Returns:
        list of Path: List of matching file paths.
    """

    paths = []
    for pattern in patterns:
        matched = sorted(glob.glob(pattern))
        paths.extend(Path(p) for p in (matched if matched else [pattern]))
    return paths


def main() -> int:
    """
    Main function to parse command line arguments, collect unique labels from CSV files, and write them to an output file.
    We describe what the command accepts, parse it, turn it into real file paths, read every file and count the labels, write the results to the output file.
    Afterwards, the decode can reuse the unique labels file to avoid decoding the same label multiple times.

    Returns:   
        int: Exit code (0 for success).
    """

    configure_stdout_utf8()
    ap = argparse.ArgumentParser(description="Extract unique labels (column 1) from CSVs.")
    ap.add_argument("inputs", nargs="+", help="CSV files or glob patterns")
    ap.add_argument("-o", "--output", required=True, help="output text file (one label per line)")
    ap.add_argument("--with-counts", action="store_true",
                    help="write 'count<TAB>label', sorted by descending count")
    args = ap.parse_args()

    paths = _resolve(args.inputs)
    counter = collect(paths)
    for warning in warn_suspicious(counter):
        print(warning)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        if args.with_counts:
            for label, count in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])):
                fh.write(f"{count}\t{label}\n")
        else:
            for label in sorted(counter):
                fh.write(f"{label}\n")

    print(f"{len(counter)} unique labels from {len(paths)} file(s) -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
