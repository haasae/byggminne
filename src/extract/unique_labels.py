"""Layer 1 helper: stream (possibly multi-GB) CSVs and emit unique labels.

Because the CSVs are huge with millions of rows, we expect the unique labels to be a small subset. 
To avoid having to decode identical labels multiple times, we extract the unique labels and save them to a text file.
Afterwards, the decode can reuse the unique labels file to avoid decoding the same label multiple times.

The raw files are `label,timestamp,value` with no header and can be gigabytes, so
we iterate line by line. The label is column 1 and may contain ':', '/', '.', '-', '#' (but not commas), so we rsplit from the
right to peel off timestamp + value. 

    python -m src.extract.unique_labels "data/raw/tasen/*.csv" -o labels.txt
    python -m src.extract.unique_labels data/raw/tasen/file.csv -o labels.tsv --with-counts
"""

import argparse # for command line argument parsing
import glob # utlility to search for files matching a pattern
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
