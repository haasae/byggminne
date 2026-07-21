"""Stateless single-label decode: prompt -> model -> extract JSON -> validate ->
fresh retry. Shared by the future API runner and reusable by the /decode skill
(extract_json + the validator).
"""
import json

from src.decode.prompt_builder import build_prompt, build_retry_suffix
from src.validate.schema_validator import validate_instance


def extract_json(text):
    """Scans `text` for the first balanced top-level JSON object and returns it as a dict.

    Models can disobey the prompt and wrap the object in explanation or json-fences. This function fixes this.
    Quotes and escapes are respected so braces inside strings do not confuse the matcher.
    Scanning happens char-by-char, so it is robust to newlines, whitespace, and other formatting variations. It returns the first balanced top-level JSON object found in the text.

    Args:
        text (str): The text to search for a JSON object.

    Returns:
        dict: The first balanced top-level JSON object found in the text.
    """

    depth = 0       # how deeply nested we are in braces
    start = None    # the index of the first '{' that starts a top-level JSON object
    in_str = False  # whether we are currently inside a string (between quotes)
    escape = False  # whether the last character was a backslash (to handle escaped quotes)
    for i, ch in enumerate(text):
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:                    # when depth returns to 0, we have found a complete top-level JSON object
                    return json.loads(text[start:i + 1])                # slice from start to i (inclusive) and parse it as JSON
    raise ValueError("no balanced JSON object found in model output")   # if we finish the loop without finding a balanced JSON object, raise an error


def decode_one(label, source_type, context, runner, validator, max_retries=2):
    """Decode one label with up to `max_retries` FRESH stateless retries.

    Each retry rebuilds the prompt from scratch and appends the validator's
    complaints as static instructions -- it is never a "you were wrong" chat
    turn, so the cold-start rule holds.

    Args:
        label (str): The label to decode.
        source_type (str): The type of the source (e.g., "Tasen").
        context (dict): Additional context for the decoding process.
        runner (object): An object that has a `complete(prompt)` method to run the model.
        validator (object): An object that has a `validate(instance)` method to validate the decoded instance.
        max_retries (int): The maximum number of retries allowed.
    
    Returns:
        dict: A dictionary containing the decoded instance, validity status, number of attempts, and raw model output if decoding failed.
    """
    
    base_prompt = build_prompt(label, source_type, context)
    prompt = base_prompt
    last_text = None
    for attempt in range(max_retries + 1):
        last_text = runner.complete(prompt)
        try:
            instance = extract_json(last_text)
        except (ValueError, json.JSONDecodeError):
            prompt = base_prompt + build_retry_suffix(
                [("(parse)", "output was not a single valid JSON object")]
            )
            continue

        errors = validate_instance(instance, validator)
        if not errors:
            return {"instance": instance, "valid": True, "attempts": attempt + 1}
        prompt = base_prompt + build_retry_suffix(errors)

    return {"instance": None, "valid": False, "attempts": max_retries + 1, "raw": last_text}
