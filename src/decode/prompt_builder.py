"""Build the self-contained, cold-start prompt for ONE label.

The same prompt text is used by the subscription path (the /decode skill pastes
it into a fresh subagent) and by the future API path (run_batch sends it as a
single user message). It carries no history and no other label's result.
"""

import argparse

from src.common.io_utils import configure_stdout_utf8, read_jsonl
from src.decode.context_pack import build_context_pack

INSTRUCTIONS = """\
You decode ONE building-energy measurement label into a single JSON object that
conforms to the OUTPUT SCHEMA in the reference context below. Follow these rules:
- Output ONLY the JSON object. No prose, no markdown, no code fences.
- Echo `raw_label` VERBATIM and copy `source_type` exactly as given.
- Partial decoding is valid: set unknown fields to null. NEVER invent a meaning
  for a code you cannot resolve -- leave it null and lower `confidence`.
- When a field rests on a knowledge-base entry, name the source file (and row
  when you can) in `reasoning`.
- Set `validated` to false. Give a calibrated `confidence` in [0, 1].
- This is a name-only round: set `data_checks` to null and `relationships` to an
  empty array [] (never null).
"""


def build_prompt(label, source_type, context):
    return (
        INSTRUCTIONS
        + "\n----- REFERENCE CONTEXT (cite these by file) -----\n"
        + context
        + "\n----- LABEL TO DECODE -----\n"
        + f"raw_label: {label}\n"
        + f"source_type: {source_type}\n"
        + "\nReturn the JSON object now."
    )


def build_retry_suffix(errors):
    """Static text appended to a FRESH prompt after a failed attempt.

    This is not a chat turn. The retry is a new stateless call whose prompt
    happens to include the validator's complaints as instructions.

    Args:
        errors (list of tuples): A list of tuples containing the location and
        message of each validation error.
    Returns:
        str: A string containing the retry instructions for the LLM.
    """

    joined = "\n".join(f"- {loc}: {msg}" for loc, msg in errors)
    return (
        "\n----- THE PREVIOUS OUTPUT WAS REJECTED -----\n"
        "Return a corrected JSON object that fixes these problems:\n" + joined
    )


def main() -> int:
    configure_stdout_utf8()
    ap = argparse.ArgumentParser(description="Print the decode prompt for one input row.")
    ap.add_argument("--input", required=True, help="batch input.jsonl")
    ap.add_argument("--index", type=int, required=True, help="0-based row index")
    args = ap.parse_args()

    rows = read_jsonl(args.input)
    row = rows[args.index]
    context, _ = build_context_pack()
    print(build_prompt(row["raw_label"], row["source_type"], context))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
