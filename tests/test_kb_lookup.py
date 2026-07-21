"""kb_lookup parses the REAL knowledge-base files -- these tests double as
guards that KB reformatting doesn't silently break the deterministic decoder."""
import pytest

from src.decode.kb_lookup import (
    component_codes,
    control_number_areas,
    deterministic_rules,
    system_code_4digit,
    system_codes,
)


def test_component_codes_resolve_known_entries():
    codes = component_codes()
    assert codes["RT"][0].startswith("Temperaturgiver")
    assert codes["RD"][0].startswith("Differansetrykkgiver")
    assert codes["RP"][0].startswith("Trykkgiver")
    assert codes["LR"][0].startswith("Frekvensomformer")
    assert codes["SB"][0].startswith("Reguleringsventil")
    assert codes["OU"][0].startswith("Undersentral")
    assert codes["IK"][0].startswith("Kuldeaggregat")
    assert codes["JP"][0].startswith("Pumpe")
    # Unused codes are excluded, citations name the file.
    assert "AA" not in codes
    assert "komponentkodeliste.md" in codes["RT"][1]


def test_system_codes_resolve_known_entries():
    codes = system_codes()
    assert codes["310"][0].startswith("Sanit")
    assert codes["320"][0] == "Varmeanlegg"
    assert codes["360"][0] == "Luftbehandling"
    assert codes["370"][0].startswith("Komfortkj")


def test_system_code_4digit_mapping():
    code4, name, citation = system_code_4digit("320")
    assert code4 == "3200" and name == "Varmeanlegg"
    assert "TFM_systemkodeliste.md" in citation
    # 320001-style callers pass the leading digits run.
    assert system_code_4digit("320001")[0] == "3200"
    assert system_code_4digit("999") is None


def test_control_number_areas_from_generated_map():
    areas = control_number_areas()
    assert areas["20053401"][0] == "tasen"
    assert areas["20056701"][0] == "skoyen"


def test_deterministic_rules_shape():
    rules = deterministic_rules()
    assert rules["point_name_keywords"]["drift"]["measurement_type"] == "status"
    assert rules["setpoint_suffixes"]["_WSP"]["function"] == "settpunkt"
    assert rules["component_letter_measurement"]["RT"] == "temperatur"


def test_missing_kb_file_is_fatal(monkeypatch, tmp_path):
    import src.decode.kb_lookup as kb
    monkeypatch.setattr(kb, "repo_root", lambda: tmp_path)
    kb.component_codes.cache_clear()
    with pytest.raises(FileNotFoundError):
        kb.component_codes()
    kb.component_codes.cache_clear()
