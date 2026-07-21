"""Layer 2a: deterministic rule-based decoding.

Turns one raw label into a schema instance using only structural tokens
(src/common/label_tokens.py) resolved against the knowledge base
(src/decode/kb_lookup.py + knowledge_base/deterministic_rules.json). Every
resolved field carries a citation in `reasoning`, unknown fields stay null, 
and a calibrated-by-policy confidence is attached.

Confidence policy (documented, deliberately simple):
  base 0.30
  +0.20 component resolved from a component code
  +0.20 primary_system from a structural system token (+0.10 if keyword hint)
  +0.10 object_type from a path/IO token
  +0.10 function or measurement_type from keyword/suffix rules
  +0.05 building resolved
  capped at 0.90 (because human validation is only way to be certain 
  conventions can lie -- see data_observations.md, FCB RT401)

Tier: FULL when >= 3 of {primary_system, component, function, measurement_type}
resolved; PARTIAL when >= 1; NONE otherwise.
"""

import re

from src.common.label_tokens import (
    EQUIPMENT_TOKEN,
    IO_POINT,
    MODBUS_TOKEN,
    POINT_CODE,
    ROOM,
    SUBSYS_COMPONENT,
    bygg_etg_of,
    controller_of,
    io_object_type,
    path_segments,
    point_token_of,
    system_token_of,
)
from src.decode.kb_lookup import (
    component_codes,
    control_number_areas,
    deterministic_rules,
    system_code_4digit,
)

FULL = "FULL"
PARTIAL = "PARTIAL"
NONE = "NONE"

CONFIDENCE_CAP = 0.90


def _empty_instance(raw_label, source_type):
    """Create a new schema instance with all fields null except raw_label and source_type."""
    return {
        "raw_label": raw_label,
        "source_type": source_type,
        "carrier": None,
        "function": None,
        "measurement_type": None,
        "unit": None,
        "object_type": None,
        "primary_system": None,
        "subsystem": None,
        "component": None,
        "location": None,
        "is_derived": None,
        "confidence": 0.3,
        "reasoning": None,
        "data_checks": None,
        "relationships": [],
        "validated": False,
        "decode_method": "rules",
        "decoded_kb_version": None,
    }


def _set(instance, field, value, clauses, clause):
    """Set a still-null field and record the citation clause."""
    if value is None or instance.get(field) is not None:
        return False
    instance[field] = value
    clauses.append(clause)
    return True


def decode_rules(raw_label, source_type):
    """Deterministically decode one label. Returns (instance, tier)."""
    rules = deterministic_rules()
    instance = _empty_instance(raw_label, source_type)
    clauses = []
    confidence = 0.30

    # --- location: controller segment / bygg token --------------------------
    control_number, ou = controller_of(raw_label)
    system_digits, bygg = system_token_of(raw_label)
    building = bygg or control_number
    if building:
        instance["location"] = {"building": building, "zone": None}
        if bygg:
            clauses.append(f"'{bygg}' token -> building {bygg}")
        else:
            area = control_number_areas().get(control_number)
            area_note = f", area {area[0]} ({area[1]})" if area else ""
            clauses.append(
                f"controller segment {control_number}-{ou} -> building "
                f"{control_number}{area_note} (bacnet_sd_label_grammar.md field 2a)"
            )
        confidence += 0.05

    # --- standalone byggN(etgM) token, e.g. 'kj maskin bygg5etg3' -------------
    bygg_alone, etg = bygg_etg_of(raw_label)
    if bygg_alone:
        if instance["location"] is None:
            instance["location"] = {"building": bygg_alone, "zone": etg}
            clauses.append(
                f"'{bygg_alone}{etg or ''}' token -> building {bygg_alone}"
                + (f", zone {etg}" if etg else "")
                + " (bacnet_sd_label_grammar.md glossary, bygg/etg tokens)"
            )
            confidence += 0.05
        elif (etg and instance["location"].get("zone") is None
              and instance["location"].get("building") == bygg_alone):
            instance["location"]["zone"] = etg
            clauses.append(f"'{bygg_alone}{etg}' token -> zone {etg} "
                           "(bacnet_sd_label_grammar.md glossary, bygg/etg tokens)")

    # --- primary system from a structural token ------------------------------
    if system_digits:
        resolved = system_code_4digit(system_digits)
        if resolved:
            code4, name, citation = resolved
            instance["primary_system"] = {"code": code4, "description": name}
            lopenummer = system_digits[3:]
            clauses.append(
                f"system token {system_digits} = legacy {system_digits[:3]} + "
                f"lopenummer {lopenummer} -> {code4} {name} ({citation}; "
                "3-digit->4-digit per decode_rules.md)"
            )
            _set(instance, "subsystem", f"system {system_digits[:3]}.{lopenummer}",
                 clauses, f"lopenummer {lopenummer} -> subsystem")
            confidence += 0.20

    # --- room zone token (e.g. 'Rom 1-03 H Temp Occ') ---------------------------
    m = ROOM.search(raw_label)
    if m:
        zone = f"Rom {m.group(1)}"
        if instance["location"] is None:
            instance["location"] = {"building": None, "zone": zone}
        else:
            instance["location"]["zone"] = zone
        clauses.append(f"'{zone}' -> location.zone (room token)")
        confidence += 0.05

    # --- combined subsystem+component token (Skoyen: '313_001_SB401') -----------
    for segment in path_segments(raw_label):
        sc = SUBSYS_COMPONENT.match(segment)
        if not sc:
            continue
        sys3, lopenummer, letters, number = sc.groups()
        resolved = system_code_4digit(sys3)
        if resolved and instance["primary_system"] is None:
            code4, name, citation = resolved
            instance["primary_system"] = {"code": code4, "description": name}
            clauses.append(f"token {segment}: {sys3} -> {code4} {name} ({citation})")
            confidence += 0.20
        sub = f"system {sys3}.{lopenummer}"
        if not resolved:
            sub += f" (code {sys3} not in the TFM list -- left uninterpreted)"
        if instance["subsystem"]:
            instance["subsystem"] = f"{instance['subsystem']}; {sub}"
            clauses.append(f"token {segment} -> subsystem {sys3}.{lopenummer}")
        else:
            _set(instance, "subsystem", sub, clauses,
                 f"token {segment} -> subsystem {sys3}.{lopenummer}")
        entry = component_codes().get(letters)
        if entry:
            meaning, citation = entry
            _set(instance, "component", f"{letters}{number} ({letters} = {meaning})",
                 clauses, f"component code {letters} = {meaning} ({citation})")
            confidence += 0.20
            mtype = rules["component_letter_measurement"].get(letters)
            _set(instance, "measurement_type", mtype, clauses,
                 f"{letters} -> measurement_type {mtype} "
                 "(deterministic_rules.json:component_letter_measurement)")
        break

    # --- component / IO point token -------------------------------------------
    point_token, suffix = point_token_of(raw_label)
    if point_token:
        core = point_token.lstrip("-")
        m = POINT_CODE.match(point_token)
        io = IO_POINT.match(core)
        if m:
            letters, side, rest = m.group(1), m.group(2), m.group(3)
            entry = component_codes().get(letters)
            if entry:
                meaning, citation = entry
                _set(instance, "component", f"{core} ({letters} = {meaning})",
                     clauses, f"component code {letters} = {meaning} ({citation})")
                confidence += 0.20
                mtype = rules["component_letter_measurement"].get(letters)
                if _set(instance, "measurement_type", mtype, clauses,
                        f"{letters} -> measurement_type {mtype} "
                        f"(deterministic_rules.json:component_letter_measurement)"):
                    _set(instance, "function", mtype, clauses,
                         f"{letters} point role -> function {mtype}")
                    confidence += 0.10
                if len(side + rest) == 3 and side in rules["side_digit_subsystem"]:
                    side_txt = rules["side_digit_subsystem"][side]
                    existing = instance.get("subsystem")
                    note = (f"first digit {side} -> {side_txt} "
                            "(komponentkodeliste.md side convention; a hint, not "
                            "a guarantee -- see data_observations.md)")
                    if existing:
                        instance["subsystem"] = f"{side_txt}; {existing}"
                        clauses.append(note)
                    else:
                        _set(instance, "subsystem", side_txt, clauses, note)
        elif io:
            _set(instance, "object_type", io.group(1), clauses,
                 f"IO point token {core} -> object_type {io.group(1)} "
                 "(decode_rules.md, BACnet object types)")
            confidence += 0.10

    # --- equipment token -> component (e.g. IK001_TEST -> IK = Kuldeaggregat) ---
    if instance["component"] is None:
        for segment in path_segments(raw_label):
            if not EQUIPMENT_TOKEN.match(segment):
                continue
            m = re.match(r"^([A-Z]{1,3})(\d{3})", segment)
            if not m:
                continue
            letters = m.group(1)
            entry = component_codes().get(letters)
            if entry:
                meaning, citation = entry
                core = m.group(1) + m.group(2)
                _set(instance, "component", f"{core} ({letters} = {meaning})",
                     clauses, f"equipment token {segment}: {letters} = {meaning} ({citation})")
                confidence += 0.20
                if segment.endswith("_TEST"):
                    clauses.append("'_TEST' suffix: commissioning/test setup, "
                                   "keep modest trust (data_observations.md)")
                break

    # --- object type from path tokens ------------------------------------------
    obj = io_object_type(raw_label)
    if _set(instance, "object_type", obj, clauses,
            f"path token -> object_type {obj} (decode_rules.md, BACnet path tokens)"):
        confidence += 0.10
    if instance["object_type"] in rules["command_object_types"]:
        for field, value in rules["command_object_types"][instance["object_type"]].items():
            if field.startswith("_"):
                continue
            _set(instance, field, value, clauses,
                 f"object_type {instance['object_type']} -> {field} {value} "
                 "(deterministic_rules.json:command_object_types)")

    # --- setpoint suffixes -------------------------------------------------------
    if suffix and suffix in rules["setpoint_suffixes"]:
        # A setpoint suffix REDEFINES the point's role: RT404_WSP is the
        # setpoint for RT404, not the sensor reading itself.
        instance["function"] = rules["setpoint_suffixes"][suffix]["function"]
        clauses.append(f"suffix {suffix} -> function settpunkt "
                       "(deterministic_rules.json:setpoint_suffixes; grammar glossary)")
        confidence += 0.10

    # --- keyword rules over the whole path ---------------------------------------
    haystack = " ".join(path_segments(raw_label)).casefold()
    matched_keywords = []
    for keyword in sorted(rules["point_name_keywords"], key=len, reverse=True):
        if keyword in haystack:
            matched_keywords.append(keyword)
            entry = rules["point_name_keywords"][keyword]
            for field, value in entry.items():
                if field.startswith("_") or field.endswith("_hint"):
                    continue
                _set(instance, field, value, clauses,
                     f"keyword '{keyword}' -> {field} {value} "
                     "(deterministic_rules.json:point_name_keywords)")
    if matched_keywords and (instance["function"] or instance["measurement_type"]
                             or instance["carrier"]):
        confidence += 0.10

    # System hint from keywords (e.g. 'heating') -- weaker than a token.
    if instance["primary_system"] is None:
        for keyword in matched_keywords:
            hint = rules["point_name_keywords"][keyword].get("system_hint")
            if hint:
                resolved = system_code_4digit(hint)
                if resolved:
                    code4, name, citation = resolved
                    instance["primary_system"] = {"code": code4, "description": name}
                    clauses.append(f"keyword '{keyword}' -> system {code4} {name} "
                                   f"({citation}; text hint, not a code match)")
                    confidence += 0.10
                break

    # --- carrier from the system medium ------------------------------------------
    if instance["carrier"] is None and instance["primary_system"] is not None:
        code4 = instance["primary_system"]["code"]
        carrier = rules.get("system_carrier", {}).get(code4[:2])
        _set(instance, "carrier", carrier, clauses,
             f"system {code4} ({code4[:2]}xx) -> carrier {carrier} "
             "(deterministic_rules.json:system_carrier)")

    # --- bookkeeping ---------------------------------------------------------------
    for segment in path_segments(raw_label):
        if MODBUS_TOKEN.match(segment):
            clauses.append(f"'{segment}' = Modbus device/register token (no NS meaning)")
            break

    if instance["component"] or instance["measurement_type"] or instance["object_type"]:
        instance["is_derived"] = False

    key_fields = [instance["primary_system"], instance["component"],
                  instance["function"], instance["measurement_type"]]
    resolved = sum(1 for f in key_fields if f is not None)
    tier = FULL if resolved >= 3 else (PARTIAL if resolved >= 1 else NONE)

    instance["confidence"] = round(min(confidence, CONFIDENCE_CAP), 2)
    instance["reasoning"] = ("; ".join(clauses)
                             if clauses else "no deterministic rule matched")
    return instance, tier
