""" Layer 2 helper: build a batch of decoder input from a list of unique labels.

Takes the text file created by `unique_labels` and reshapes it into JSON Lines
for the decoder. Each line is a JSON object with two fields, `raw_label` and
`source_type`:

    {"raw_label": "some label", "source_type": "bacnet"}

`source_type` is passed on the command line and is currently one of "kiona",
"bacnet", or "other". The set may grow later, but for now the decoder only ever
sees these three.

The batch deliberately carries NO semantic fields -- only what the decoder is
allowed to see. It's written to the path given by -o (conventionally
`input.jsonl`); the decoder later reads that file and emits its own `outputs.jsonl`

Usage:

    python -m src.extract.build_batch labels.txt --source-type bacnet \
        -o data/eval/batches/b001/input.jsonl
"""

import argparse
from pathlib import Path

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
