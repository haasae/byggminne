"""Shared structural tokens/helpers for BACnet/SD raw labels.

Single home for the vendor-specific label grammar helpers (see
knowledge_base/bacnet_sd_label_grammar.md) so the decode rules engine and the
profile relationship checker cannot drift apart. Heuristics are deliberately
small and covered by tests with real-shaped labels.
"""
import re

# Controller segment = everything between ':' and '/' (grammar field 2):
# `<controlnumber>-<rest>` where rest is `OU001` (Tasen) or a name (`Skoyen`).
CONTROLLER = re.compile(r"^(\d{8})-([\w-]+)$")
# System token, e.g. `320001`, `320001_bygg5`, or Skoyen's `SK320001`
# (an optional 1-2 letter prefix before the digits).
SYSTEM_TOKEN = re.compile(r"^(?:[A-Z]{1,2})?(\d{5,7})(?:_(bygg\w+))?$")
# Equipment tokens, e.g. `IK001_TEST`, `Spillvannspumpe_P2`.
EQUIPMENT_TOKEN = re.compile(r"^(?:[A-Z]{1,3}\d{3}(?:_\w+)?|[A-Za-z]+pumpe_P\d+)$")
# Component point code, e.g. `-RT401` / `RT507` / `SB41` (2 letters + 2-3 digits).
POINT_CODE = re.compile(r"^-?([A-Z]{2})(\d)(\d{1,2})$")
# Component code embedded at the END of a larger segment, after a separator:
# Skoyen `563_H26-SB602` -> SB602. Uppercase-only keeps free text out; the
# part before the separator (e.g. `H26`) stays uninterpreted -- never invent.
# ponytail: letters are gated only by komponentkodeliste (330 pairs, incl.
# collision-prone IP/SW/MV); restrict to a curated point-family allowlist if a
# vendor tail ever false-positives -- see docs/tokenizer_failure_modes.md.
EMBEDDED_POINT_TAIL = re.compile(r"[-_ ]([A-Z]{2}\d{2,3})$")
# Modbus device/register token, e.g. `2017_adr1`, `320x_adr106`.
MODBUS_TOKEN = re.compile(r"^([0-9x]{3,5})_adr(\d+)$")
# Standalone building(+floor) token inside a free-text segment, e.g.
# `kj maskin bygg5etg3` -> bygg5 / etg3. The `_bygg5` suffix of a system token
# is NOT matched here ('_' is a word character), SYSTEM_TOKEN owns that case.
BYGG_ETG = re.compile(r"\b(bygg\d+)(etg\d+)?\b", re.IGNORECASE)
# Trailing point-name setpoint suffixes.
SETPOINT_SUFFIX = re.compile(r"_(?:SP|WSP)$")

# BACnet path tokens -> object_type (decode_rules.md, BACnet section).
PATH_OBJECT_TOKENS = {
    "analoge innganger": "AI",
    "analoge utganger": "AO",
    "analoge verdier": "AV",
    "binaere innganger": "BI",
    "binaere utganger": "BO",
    "binære innganger": "BI",
    "binære utganger": "BO",
    "innganger": None,   # ambiguous alone (could be digital or analog)
    "utganger": None,
}
# Bare I/O point names like `BI3` / `BO1` / `MV1` / Skoyen's `AI-1128`.
IO_POINT = re.compile(r"^(AV|BV|MV|AI|AO|BI|BO|MI|MO)-?(\d+)$")
# Skoyen `NNN_NNN_XXNNN` point layout: subsystem + component in one token,
# e.g. `313_001_SB401` = subsystem 313.001, component SB401.
SUBSYS_COMPONENT = re.compile(r"^(\d{3})_(\d{3})_([A-Z]{2})(\d{2,3})$")
# Room zone token in point names, e.g. `Rom 1-03`.
ROOM = re.compile(r"\bRom (\d+-\d+)\b", re.IGNORECASE)


def path_segments(raw_label):
    """Split `node:controller/path` into the path's '.'-separated segments.

    The trailing `#NN` tag is dropped (constant, meaning unknown -- grammar
    field 6). Leading '-' on FCB point tokens is preserved for POINT_CODE.
    """
    path = raw_label.split(":", 1)[-1]
    path = path.split("/", 1)[-1]
    segments = [seg.strip() for seg in path.split(".")]
    return [seg for seg in segments if seg and not seg.startswith("#")]


def controller_of(raw_label):
    """(control_number, rest) from the ':'..'/' segment, e.g.
    ('20053401', 'OU001') or ('20056703', 'Skoyen'); (None, None) otherwise."""
    if ":" not in raw_label:
        return None, None
    segment = raw_label.split(":", 1)[1].split("/", 1)[0]
    m = CONTROLLER.match(segment)
    return (m.group(1), m.group(2)) if m else (None, None)


def system_token_of(raw_label):
    """(system_digits, bygg) from the first system-token segment, e.g.
    ('320001', 'bygg5'); (None, None) when absent."""
    for segment in path_segments(raw_label):
        m = SYSTEM_TOKEN.match(segment)
        if m:
            return m.group(1), m.group(2)
    return None, None


def point_token_of(raw_label):
    """The last segment that parses as a component/IO point, with any setpoint
    suffix split off: returns (token, suffix) e.g. ('-RT404', '_WSP')."""
    for segment in reversed(path_segments(raw_label)):
        suffix = None
        core = segment
        m = SETPOINT_SUFFIX.search(core)
        if m:
            suffix, core = m.group(0), core[: m.start()]
        if POINT_CODE.match(core) or IO_POINT.match(core.lstrip("-")):
            return core, suffix
        m = EMBEDDED_POINT_TAIL.search(core)
        if m:
            return m.group(1), suffix
    return None, None


def bygg_etg_of(raw_label):
    """(building, zone) from a standalone byggN(etgM) token, e.g.
    ('bygg5', 'etg3') from 'kj maskin bygg5etg3'; (None, None) when absent."""
    m = BYGG_ETG.search(raw_label)
    return (m.group(1), m.group(2)) if m else (None, None)


def point_role(raw_label):
    """(letters, side_digit) from a component point code; side: 4=tur, 5=retur.

    The side meaning is confirmed only for codes with THREE digits (grammar:
    'whenever a two-letter code is followed by three digits') -- a 2-digit code
    like SB41 yields no role here.
    """
    for segment in raw_label.split(":", 1)[-1].split("."):
        m = POINT_CODE.match(segment.strip())
        if m and len(m.group(2) + m.group(3)) == 3:
            return m.group(1), m.group(2)
    return None, None


def io_object_type(raw_label):
    """BACnet object type from path tokens or bare IO point names, else None."""
    segments = path_segments(raw_label)
    for segment in segments:
        mapped = PATH_OBJECT_TOKENS.get(segment.casefold())
        if mapped:
            return mapped
    for segment in reversed(segments):
        m = IO_POINT.match(segment.lstrip("-"))
        if m:
            return m.group(1)
    return None


def group_keys(raw_label):
    """(kind, key) group memberships derived from the label's structure."""
    keys = []
    number, ou = controller_of(raw_label)
    if number and ou:
        keys.append(("same_controller", f"{number}-{ou}"))
    segments = path_segments(raw_label)
    for i, segment in enumerate(segments):
        m = SYSTEM_TOKEN.match(segment)
        if m:
            keys.append(("same_system", segment))
        elif EQUIPMENT_TOKEN.match(segment):
            keys.append(("same_equipment", segment))
        elif MODBUS_TOKEN.match(segment) and i > 0:
            # A Modbus device token is an equipment identity (room controller
            # etc.). Bus-qualified: addresses repeat across buses, so
            # `ModbusRTU.2017_adr1` and `ModbusRTU2.2017_adr1` stay distinct.
            keys.append(("same_equipment", f"{segments[i - 1]}.{segment}"))
    return keys
