"""Layer 2b: retrieval/inheritance from validated decodes.

The knowledge base accumulates validated decodings in
knowledge_base/validated_decodes.jsonl (seeded from the b001 gold set; grows
with every human/data confirmation -- that IS the KB-accumulation loop of
CLAUDE.md section 3). This layer answers two questions:

- **exact**: have we validated THIS label before? -> return the stored decode.
- **sibling**: have we validated a structurally identical label (same shape,
  different digits: other OU / control number / lopenummer / address)? -> its
  decode can seed fields the rules engine could not resolve.
"""

import re
from functools import lru_cache

from src.common.io_utils import read_jsonl, repo_root
from src.common.label_tokens import path_segments

STORE_FILE = "knowledge_base/validated_decodes.jsonl"

# Fields that may rest on point-specific data observations -- exact-name only.
OBSERVATION_FIELDS = ("function", "unit", "subsystem", "measurement_type")
# Structure-derived fields -- safe to transfer to any structural sibling.
STRUCTURAL_FIELDS = ("primary_system", "carrier",
                     "component", "is_derived", "object_type")

_DIGITS = re.compile(r"\d+")


def signature(raw_label):
    """Structural signature: digit runs parameterized, case folded.

    'OU001 ... -RT401' and 'OU002 ... -RT402' share a signature; '-RT401' vs
    '-RD401' do not.
    """

    return _DIGITS.sub("#", raw_label).casefold()


def point_name(raw_label):
    """The final path segment (the point's own name), e.g. '-RT401',
    'Kjole_Drift-', 'Effective Set point'.
    
    Returns the last segment of the path derived from the raw label. 
    If the path is empty, returns the raw label itself.
    """

    segments = path_segments(raw_label)
    return segments[-1] if segments else raw_label


@lru_cache(maxsize=None)
def _store(path_key=None):
    """Load the validated decodes store, returning (rows, by_label, by_signature).
    
    Args:
        path_key (str, optional): Relative path to the validated decodes file.
            Defaults to None, which uses the STORE_FILE constant.
    
    Returns:
        tuple: A tuple containing:
            - list: List of rows (each row is a dict).
            - dict: Mapping of raw_label to row.
            - dict: Mapping of signature to list of rows with that signature.
    """

    path = repo_root() / (path_key or STORE_FILE)
    if not path.exists():
        return [], {}, {}
    rows = read_jsonl(path)
    by_label = {row["raw_label"]: row for row in rows}
    by_signature = {}
    for row in rows:
        by_signature.setdefault(signature(row["raw_label"]), []).append(row)
    return rows, by_label, by_signature


def clear_cache():
    _store.cache_clear()


def retrieve(raw_label, store_path=None):
    """('exact', row) | ('sibling', row) | None for a raw label."""

    _rows, by_label, by_signature = _store(store_path)
    hit = by_label.get(raw_label)
    if hit is not None:
        return "exact", hit
    siblings = by_signature.get(signature(raw_label), [])
    if siblings:
        # Deterministic choice: prefer an exact point-name match (more fields
        # transfer), then the lexicographically first sibling.
        name = point_name(raw_label)
        same_name = [s for s in siblings if point_name(s["raw_label"]) == name]
        pool = same_name or siblings
        return "sibling", sorted(pool, key=lambda r: r["raw_label"])[0]
    return None


def inherit_fields(template, raw_label):
    """{field: (value, note)} a sibling template donates to `raw_label`.

    STRUCTURAL fields only -- observation-prone fields (OBSERVATION_FIELDS)
    never inherit, whatever the name similarity (see module docstring). Values
    are donations; the caller decides precedence (rules-resolved fields win).

    Args:
        template (dict): A schema instance from which to inherit fields.
        raw_label (str): The raw label of the new instance that will inherit fields.
    
    Returns:
        dict: A dictionary mapping each inherited field to a tuple of (value, note),
              where 'value' is the inherited value and 'note' explains the inheritance.
    """

    donations = {}
    for field in STRUCTURAL_FIELDS:
        value = template.get(field)
        if value is None:
            continue
        donations[field] = (
            value,
            f"inherited from validated sibling '{template['raw_label']}'"
            " (structural fields only)",
        )
    return donations
