""" 
Takes the text file created by `unique_labels` and reshapes it into JSON Lines for the decoder. 
Each line is a JSON object with two fields: `raw_label` and `source_type`. 
The `source_type` is provided by the user on the command line and can be one of "kiona", "bacnet", or "other". 
Possible source types may be expanded in the future, but for now the decoder will only see these three values.

It produces a file called `input.jsonl` that can be used as input to the decoder. 
The decoder will read this file and produce an output file called `outputs.jsonl`.
In `input.jsonl` an output line looks like this:
{"raw_label": "some label", "source_type": "bacnet"}

The input.jsonl deliberately holds NO semantic fields -- only what the decoder is allowed to see.

    python -m src.extract.build_batch labels.txt --source-type bacnet \
        -o data/eval/batches/b001/input.jsonl
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

"""
- sys.path.insert(0, ...) inserts this directory path at index 0, which is the front of the list of directories Python searches for modules. 
This allows us to import modules from the src directory.
- __file__ is this file's own path (.../src/extract/unique_labels.py).
- .parents[2] goes up two levels to the root of the project (the parent of src).
"""

from src.common.io_utils import configure_stdout_utf8, write_jsonl

def main() -> int:
    """
    Main function to build a batch of decoder input from a list of unique labels.
    It reads a text file containing unique labels, processes them, and writes them to a JSON Lines file for the decoder.

    First it parses command line arguments to get the input labels file, output file path, and source type. 
    The core loop reads each label from the input file, strips whitespace, and ensures that each label is unique.

    Requires:
        - A text file with one raw_label per line (the output of unique_labels).
        - Uniform source type for all labels in the input, specified as a command line argument.

    Returns:
        int: Exit code (0 for success).
    """

    configure_stdout_utf8()
    ap = argparse.ArgumentParser(description="Build decoder input.jsonl from a label list.")
    ap.add_argument("labels", help="text file with one raw_label per line")
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--source-type", required=True, choices=["kiona", "bacnet", "other"])
    args = ap.parse_args()

    rows = []
    seen = set()
    for line in Path(args.labels).read_text(encoding="utf-8").splitlines():
        label = line.strip()
        if not label:
            continue
        if "\t" in label: 
            # the user may have used the --with-counts option in unique_labels.  
            # this produces lines like 'count<TAB>label'. We only want the label part.  
            label = label.split("\t", 1)[1]
        if label in seen:
            continue
        seen.add(label)
        rows.append({"raw_label": label, "source_type": args.source_type})

    write_jsonl(args.output, rows)
    print(f"{len(rows)} input rows -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
