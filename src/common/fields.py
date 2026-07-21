"""The field registry: the single source of truth for the scoring policy.

field_compare, metrics, and report all read tiers / comparison kinds from here,
so changing how a field is scored (or whether it is scored at all) happens in
exactly one place. See docs/EVALUATION.md and CLAUDE.md section 5.
"""
from dataclasses import dataclass
from typing import Optional, Tuple

# Comparison kinds.
ENUM = "enum"            # schema enum, ASCII -> compared verbatim
CODE = "code"            # NS system code -> headline = first-3-digit prefix
FREE_TEXT = "free_text"  # Norwegian free text -> normalized-exact
BOOL = "bool"            # boolean -> compared directly

# Tiers.
CORE = "core"            # must-be-exact backbone
NICE = "nice"            # nice-to-have


@dataclass(frozen=True)
class FieldSpec:
    path: str                                      # dotted path into a decoded-label instance
    kind: str                                      # ENUM | CODE | FREE_TEXT | BOOL
    tier: str                                      # CORE | NICE
    applies_to: Optional[Tuple[str, ...]] = None   # source_types where a non-null value is expected (metadata)


# Fields scored this round. object_type is only expected on bacnet rows; on other
# rows gold is null, so null==null keeps it correct and "non-trivial" accuracy
# (gold-non-null only) naturally restricts it to bacnet.
SCORED_FIELDS = (
    FieldSpec("carrier", ENUM, CORE),
    FieldSpec("measurement_type", ENUM, CORE),
    FieldSpec("object_type", ENUM, CORE, applies_to=("bacnet",)),
    FieldSpec("is_derived", BOOL, CORE),
    FieldSpec("primary_system.code", CODE, CORE),
    FieldSpec("function", FREE_TEXT, NICE),
    FieldSpec("unit", FREE_TEXT, NICE),
    FieldSpec("subsystem", FREE_TEXT, NICE),
    FieldSpec("component", FREE_TEXT, NICE),
    FieldSpec("location.building", FREE_TEXT, NICE),
    FieldSpec("location.zone", FREE_TEXT, NICE),
    FieldSpec("primary_system.description", FREE_TEXT, NICE),
)

# Documented, intentionally NOT scored this round.
EXCLUDED_FIELDS = (
    "raw_label",       # the join key
    "source_type",     # given in the batch input
    "reasoning",       # free prose, ungradeable
    "validated",       # always pred=false / gold=true
    "relationships",   # empty this round
    "data_checks",     # null this round (name-only decoding)
    "confidence",      # used for calibration, not correctness
)

_BY_PATH = {f.path: f for f in SCORED_FIELDS}


def scored_fields() -> Tuple[FieldSpec, ...]:
    return SCORED_FIELDS


def core_fields() -> Tuple[FieldSpec, ...]:
    return tuple(f for f in SCORED_FIELDS if f.tier == CORE)


def spec_for(path: str) -> FieldSpec:
    return _BY_PATH[path]


def get_value(instance, dotted_path):
    """Walk a dotted path; return None if any segment is missing or null.

    Distinguishes nothing from null on purpose -- both read as "no value", which
    is what the scorer wants (a missing nested object and an explicit null are
    treated the same)."""
    cur = instance
    for part in dotted_path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
        if cur is None:
            return None
    return cur
