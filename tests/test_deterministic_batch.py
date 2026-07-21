"""End-to-end: the deterministic driver on the real b001 input, zero tokens.

Success bars from the plan: 100% of decoded rows schema-valid; the seven
legacy-320001 labels emit the exact 4-digit code; the store returns the
validated gold rows for exact matches.
"""
from src.common.io_utils import read_jsonl, repo_root
from src.decode.deterministic_batch import decode_deterministic
from src.validate.schema_validator import build_validator, validate_instance


def _b001_rows():
    return read_jsonl(repo_root() / "data/eval/batches/b001/input.jsonl")


def test_b001_all_rows_decode_and_validate():
    validator = build_validator()
    rows = _b001_rows()
    assert len(rows) == 19
    for row in rows:
        instance, tier, method = decode_deterministic(row["raw_label"], row["source_type"])
        assert validate_instance(instance, validator) == [], row["raw_label"]
        assert tier in ("FULL", "PARTIAL"), row["raw_label"]   # nothing unusable
        assert instance["decode_method"] in ("rules", "retrieval", "rules+retrieval")


def test_b001_exact_store_hits_return_validated_gold():
    # Every b001 label is in the seeded store -> all are exact retrieval hits.
    for row in _b001_rows():
        instance, _tier, method = decode_deterministic(row["raw_label"], row["source_type"])
        assert method == "retrieval"
        assert instance["validated"] is True


def test_novel_sibling_gets_rules_reading_not_the_observation():
    # OU004's RT401 is NOT in the store; its OU001 sibling is. Only OU001 was
    # data-verified as outdoor, so OU004 keeps the honest rules reading and
    # its own future data check decides (observations never inherit).
    label = "A20-P2-APP019:20053401-OU004/FCB.Local Application.-RT401.#85"
    instance, tier, method = decode_deterministic(label, "bacnet")
    assert instance["validated"] is False
    assert not (instance["function"] or "").startswith("utetemperatur")
    assert instance["measurement_type"] == "temperatur"    # rules-derived
    assert instance["raw_label"] == label


def test_novel_rt402_gets_rules_reading_not_outdoor():
    label = "A20-P2-APP019:20053401-OU001/FCB.Local Application.-RT402.#85"
    instance, tier, method = decode_deterministic(label, "bacnet")
    # RT402 must NOT inherit the RT401-specific outdoor observation.
    assert not (instance["function"] or "").startswith("utetemperatur")
    assert instance["measurement_type"] == "temperatur"
    assert instance["component"].startswith("RT402")


def test_seven_legacy_codes_emit_4_digit():
    heating = 0
    for row in _b001_rows():
        instance, _t, _m = decode_deterministic(row["raw_label"], row["source_type"])
        code = (instance.get("primary_system") or {}).get("code")
        if "320001" in row["raw_label"] or "Heating control" in row["raw_label"]:
            assert code == "3200", row["raw_label"]
            heating += 1
        if "Spillvannspumpe" in row["raw_label"]:
            assert code == "3100", row["raw_label"]   # sanitary, the 7th fix
    assert heating == 6
