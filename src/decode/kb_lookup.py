"""Parses the knowledge-base reference files, caching them in memory for fast lookups

The deterministic rules engine resolves codes through these parsers instead of
hardcoding meanings (the KB is the source of truth).
Each lookup returns (value, citation) so every resolved field can cite its
file + row, exactly like an LLM decode must. Parsed once per process (cached),
a missing KB file is a hard error, never silent skip.
"""

import hashlib
import json
import re
from functools import lru_cache

from src.common.io_utils import repo_root

KOMPONENT_FILE = "knowledge_base/komponentkodeliste_dir/komponentkodeliste.md"
SYSTEM_FILE = "knowledge_base/TFM_systemkodeliste_dir/TFM_systemkodeliste.md"
AREA_FILE = "knowledge_base/control_number_area_map.md"
RULES_FILE = "knowledge_base/deterministic_rules.json"

# `|**RT**|**Temperaturgiver**|...`
# The meaning cell is captured whole and stripped of markup, because bold can
# be broken across <br> (e.g. `|**KH**|**Transportenhet (**<br>**...)**|`).
_PIPE_ROW = re.compile(r"^\|\*\*([A-ZÆØÅ]{1,2})\*\*\|([^|]+)\|")
# HTML table cells in the TFM systemkodeliste (same shape PDF-parser handles).
_TR = re.compile(r"<tr>(.*?)</tr>", re.S)
_CELL = re.compile(r"<t[hd][^>]*>(.*?)</t[hd]>", re.S)
_LEADING_CODE = re.compile(r"^(\d{2,3})\s+(.+)$")
# `| 20053401 | tasen | ... |` rows of the auto-generated area map.
_AREA_ROW = re.compile(r"^\|\s*(\d{8})\s*\|\s*(\S+)\s*\|")


def _read(rel):
    """Read a knowledge-base file relative to the repo root, error if missing.
    Args:
        rel (str): Relative path to the knowledge-base file.

    Returns:
        str: Contents of the knowledge-base file.
    """

    path = repo_root() / rel
    if not path.exists():
        raise FileNotFoundError(
            f"knowledge-base file missing: {rel} (looked at {path}). "
            "The deterministic decoder cannot run without it."
        )
    return path.read_text(encoding="utf-8")


def _strip_html(text):
    """Remove HTML tags and replace <br> with spaces, then collapse whitespace.
    Args:
        text (str): Text containing HTML tags.
    Returns:
        str: Text with HTML tags removed and whitespace collapsed.
    """

    text = text.replace("<br/>", " ").replace("<br>", " ")
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


@lru_cache(maxsize=1)
def component_codes():
    """{code: (meaning, citation)} for NS 3457-8 component letter codes.
    The citation is the line number in the source file, so that every resolved
    field can cite its source exactly like an LLM decode must. The file repeats
    family headers, so the first definition wins.
    Returns:
        dict: A dictionary mapping component codes to their meanings and citations.
    """
    out = {}
    for line_no, line in enumerate(_read(KOMPONENT_FILE).splitlines(), 1):
        m = _PIPE_ROW.match(line.strip())
        if not m:
            continue
        code = m.group(1)
        meaning = m.group(2).replace("<br>", " ").replace("**", "")
        meaning = re.sub(r"\s+", " ", meaning).strip()
        if not meaning or meaning.lower() in ("ikke i bruk", "bør ikke brukes"):
            continue
        # First definition wins (the file repeats family headers).
        out.setdefault(code, (meaning, f"komponentkodeliste.md line {line_no} ('{code}')"))
    return out


@lru_cache(maxsize=1)
def system_codes():
    """{3-digit code: (name, citation)} for TFM/NS 3451 system codes."""
    out = {}
    text = _read(SYSTEM_FILE)
    for tr in _TR.findall(text):
        cells = _CELL.findall(tr)
        if not cells:
            continue
        first = _strip_html(cells[0])
        m = _LEADING_CODE.match(first)
        if not m:
            continue
        code, name = m.group(1), m.group(2).strip()
        out.setdefault(code, (name, f"TFM_systemkodeliste.md row '{code} {name}'"))
    return out


@lru_cache(maxsize=1)
def control_number_areas():
    """{control_number: (area, citation)} from the auto-generated map."""
    out = {}
    for line in _read(AREA_FILE).splitlines():
        m = _AREA_ROW.match(line.strip())
        if m:
            number, area = m.group(1), m.group(2)
            out[number] = (area, f"control_number_area_map.md row '{number}'")
    return out


@lru_cache(maxsize=1)
def deterministic_rules():
    """The curated keyword/suffix/token rules (see the JSON for structure)."""
    return json.loads(_read(RULES_FILE))


def decoder_state_version():
    """Hash over the deterministic decoder's own knowledge (rules JSON +
    validated store). The context-pack kb_version does not cover these, so
    deterministic runs stamp this too for attributability.
    Returns:
        str: A 12-character hex digest representing the current state of the decoder's knowledge.
    """
    h = hashlib.sha256()
    for rel in (RULES_FILE, "knowledge_base/validated_decodes.jsonl"):
        path = repo_root() / rel
        h.update(path.read_bytes() if path.exists() else b"absent")
    return h.hexdigest()[:12]


def system_code_4digit(digits):
    """Legacy 3-digit shorthand -> (4-digit code, name, citation), or None.

    `320001` callers pass the leading 3 digits ('320'); output is the 4-digit
    NS 3451 form per knowledge_base/decode_rules.md ('320' -> '3200').
    Args:
        digits (str): The leading 3 digits of a system code.
    Returns:
        tuple or None: A tuple containing the 4-digit code, name, and citation if 
        found; otherwise, None.
    """
    entry = system_codes().get(digits[:3])
    if entry is None:
        return None
    name, citation = entry
    return digits[:3] + "0", name, citation
