"""Runtime lookups over knowledge_base/brick_mapping.json.

Same doctrine as src/decode/kb_lookup.py: parsed once per process (cached), a
missing KB file is FATAL, and every lookup returns (value, citation) so graph
triples stay attributable. Unknown inputs map to the generic base class
(Point / Equipment / System) -- never invent a more specific one.
"""
import hashlib
import json
import re
from functools import lru_cache

from src.common.io_utils import repo_root

MAPPING_FILE = "knowledge_base/brick_mapping.json"

BRICK = "https://brickschema.org/schema/Brick#"
QUDT_UNIT = "http://qudt.org/vocab/unit/"

# Leading NS 3457-8 letters of a component/equipment token, e.g. 'RT401 (...)'.
_LETTERS = re.compile(r"^([A-Z]{1,3})\d")


def _read():
    path = repo_root() / MAPPING_FILE
    if not path.exists():
        raise FileNotFoundError(
            f"knowledge-base file missing: {MAPPING_FILE} (looked at {path}). "
            "The Brick emitter cannot run without it."
        )
    return path.read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def brick_mapping():
    return json.loads(_read())


def mapping_version():
    """Short hash of the mapping file, stamped into emit_meta.json."""
    return hashlib.sha256(_read().encode("utf-8")).hexdigest()[:12]


def component_letters(component_field):
    """The NS letters of a decoded `component` value ('RT401 (RT = ...)' -> 'RT')."""
    if not component_field:
        return None
    m = _LETTERS.match(component_field)
    return m.group(1) if m else None


def _rule_matches(when, row):
    if "function_contains" in when:
        function = (row.get("function") or "").casefold()
        if when["function_contains"] not in function:
            return False
    if "measurement_type" in when and row.get("measurement_type") != when["measurement_type"]:
        return False
    if "component_letters" in when:
        if component_letters(row.get("component")) != when["component_letters"]:
            return False
    return True


def point_class(row):
    """(Brick point class, citation) for a decoded row; fallback ('Point', ...)."""
    for i, rule in enumerate(brick_mapping()["point_class_rules"]):
        if "class" not in rule:
            continue
        if _rule_matches(rule.get("when", {}), row):
            return rule["class"], (f"brick_mapping.json:point_class_rules[{i}] "
                                   f"({rule['_source']})")
    return "Point", "brick_mapping.json:point_class_rules fallback (no rule matched)"


def equipment_class(token):
    """(Brick equipment class, citation) for an equipment token / group key."""
    mapping = brick_mapping()
    letters = component_letters(token)
    entry = mapping["equipment_letter_class"].get(letters) if letters else None
    if entry:
        return entry["class"], (f"brick_mapping.json:equipment_letter_class.{letters} "
                                f"({entry['_source']})")
    lowered = (token or "").casefold()
    for needle, entry in mapping["equipment_token_class"].items():
        if needle.startswith("_"):
            continue
        if needle in lowered:
            return entry["class"], (f"brick_mapping.json:equipment_token_class.{needle} "
                                    f"({entry['_source']})")
    return "Equipment", "brick_mapping.json fallback: unknown equipment token"


def system_class(code4):
    """(Brick system class, citation) for a 4-digit NS code; fallback ('System', ...)."""
    entry = brick_mapping()["system_prefix_class"].get((code4 or "")[:2])
    if entry and "class" in entry:
        return entry["class"], (f"brick_mapping.json:system_prefix_class.{code4[:2]} "
                                f"({entry['_source']})")
    return "System", "brick_mapping.json fallback: NS prefix not mapped"


def unit_iri(unit):
    """(full QUDT unit IRI, citation) for a decoded unit string, or (None, None)."""
    entry = brick_mapping()["unit_map"].get(unit or "")
    if entry and "unit" in entry:
        return QUDT_UNIT + entry["unit"], f"brick_mapping.json:unit_map.{unit}"
    return None, None


def mapped_class_names():
    """Every Brick class name the mapping can emit (for the class-list test)."""
    mapping = brick_mapping()
    names = {"Point", "Equipment", "System", "Site", "Building"}
    names.update(e["class"] for e in mapping["system_prefix_class"].values()
                 if isinstance(e, dict) and "class" in e)
    names.update(r["class"] for r in mapping["point_class_rules"] if "class" in r)
    names.update(e["class"] for e in mapping["equipment_letter_class"].values()
                 if isinstance(e, dict) and "class" in e)
    names.update(e["class"] for e in mapping["equipment_token_class"].values()
                 if isinstance(e, dict) and "class" in e)
    return sorted(names)
