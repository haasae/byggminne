"""
This is a blueprint for a batch decode workflow. 
All actual decode intelligence lives in decode_label.py, not here. This script is just a wrapper that reads a batch input.jsonl, decodes each label independently with one fresh API call, and writes outputs.jsonl + run_meta.json.
It is not yet implemented, but the plan is to have a single command that takes a batch of labels and decodes them all in one go.

Future plan: Implement the API-mode batch decode functionality.
Current workflow: The decoder is run in subscription mode, which uses the /decode skill. 
This is the current recommended way to decode a batch of labels. 

Reads a batch input.jsonl, decodes each label independently with one fresh API
call, and writes outputs.jsonl + run_meta.json. Requires the 'anthropic' package
and ANTHROPIC_API_KEY; until the project is deployed, run the /decode skill
instead.

    python -m src.decode.run_batch --input data/eval/batches/<id>/input.jsonl \
        --out-dir runs/<id> --model <model-id>
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# I/O helpers, the context pack, the per-label decoder, the runner, and the validator
from src.common.io_utils import (
    configure_stdout_utf8,
    read_jsonl,
    write_json,
    write_jsonl,
)
from src.decode.context_pack import build_context_pack
from src.decode.decode_label import decode_one
from src.decode.runner import ApiRunner
from src.validate.schema_validator import build_validator


def main() -> int:
    """
    Main function to decode a batch of labels via the LLM API. 
    It reads an input JSON Lines file containing raw labels and their source types
    Decodes each label independently by `decode_one` (which comes from decode_label), and writes the results to an output directory.
    If parsing or validation fails, it rebuilds the prompt from scratch and appends the validator's complaints as static instructions up to the max retries limit. The re-build keeps every model call stateless, so no kabek's result depends on another's.
    """

    configure_stdout_utf8()
    ap = argparse.ArgumentParser(description="Decode a batch via the LLM API (future mode).")
    ap.add_argument("--input", required=True) # the input.jsonl file with raw_label + source_type for each label to decode.
    ap.add_argument("--out-dir", required=True) # the output directory where outputs.jsonl and run_meta.json will be written.
    ap.add_argument("--model", required=True) # the model to use for decoding (e.g., claude-2, claude-instant-1, gpt-4o, etc.)
    ap.add_argument("--max-retries", type=int, default=2) # the maximum number of retries for decoding a label if the API call fails or returns an invalid result.
    args = ap.parse_args()

    rows = read_jsonl(args.input)
    context, kb_version = build_context_pack() # build the context pack for decoding, which includes the knowledge base version.
    validator = build_validator() # build the schema validator to check if the decoded output conforms to the expected schema.
    runner = ApiRunner(args.model) # create an API runner that will handle the API calls to the LLM for decoding.

    outputs = []
    invalid = 0
    for row in rows:
        result = decode_one(
            row["raw_label"], row["source_type"], context, runner, validator, args.max_retries
        )
        if result["valid"]:
            outputs.append(result["instance"])
        else:
            invalid += 1
            outputs.append({
                "raw_label": row["raw_label"],
                "source_type": row["source_type"],
                "schema_invalid": True,
                "raw": result.get("raw"),
            })

    out_dir = Path(args.out_dir)
    write_jsonl(out_dir / "outputs.jsonl", outputs) # write the decoded outputs to outputs.jsonl in the specified output directory.
    write_json(out_dir / "run_meta.json", { # write metadata (which model, which kb_version, which input file, etc.) to run_meta.json, with the purpose of keeping track of the run's context and parameters.
        "model": args.model,
        "kb_version": kb_version,
        "input": args.input,
        "n": len(rows),
        "schema_invalid": invalid,
        "max_retries": args.max_retries,
    })
    print(f"decoded {len(rows)} labels ({invalid} schema-invalid) -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
