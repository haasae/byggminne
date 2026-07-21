from src.profile.cross_check import (
    CONFLICT,
    INCONCLUSIVE,
    PASS,
    build_data_checks,
    check_av_trap,
    check_binary_expected,
    check_dead_point,
    check_energy_monotonic,
    check_file_kind,
    check_range,
    cross_check,
    run_checks,
)
from src.validate.schema_validator import build_validator, validate_instance


def _stats(**over):
    base = {
        "raw_label": "L", "n_rows": 100, "n_bad_values": 0,
        "files": ["X AV punkter 2025.csv"], "file_kinds": ["AV"],
        "first_ts": "2025-01-01 00:00:00.000", "last_ts": "2025-06-01 00:00:00.000",
        "n_out_of_order": 0, "n_num": 100, "min": 0.0, "max": 1.0,
        "mean": 0.5, "std": 0.5, "zero_fraction": 0.5, "n_negative": 0,
        "distinct_count": 2, "distinct_capped": False, "values": [0.0, 1.0],
        "is_binary": True, "monotonic_nondecreasing": False, "n_decreases": 3,
    }
    base.update(over)
    return base


# --- individual checks -------------------------------------------------------

def test_binary_expected_pass_and_conflict():
    decoded = {"measurement_type": "status"}
    assert check_binary_expected(decoded, _stats())[0] == PASS
    many = _stats(distinct_count=7, values=None, is_binary=False)
    assert check_binary_expected(decoded, many)[0] == CONFLICT
    capped = _stats(distinct_count=None, distinct_capped=True, values=None, is_binary=False)
    assert check_binary_expected(decoded, capped)[0] == CONFLICT
    # BO command counts as a binary guess even without measurement_type=status.
    assert check_binary_expected({"object_type": "BO"}, _stats())[0] == PASS
    # Not applicable for an analog guess.
    assert check_binary_expected({"measurement_type": "temperatur"}, _stats())[0] == "N/A"


def test_av_trap_fires_on_two_valued_analog_guess():
    decoded = {"measurement_type": "temperatur", "object_type": "AV"}
    verdict, evidence = check_av_trap(decoded, _stats())
    assert verdict == CONFLICT and "AV trap" in evidence
    analog = _stats(distinct_count=None, distinct_capped=True, values=None, is_binary=False)
    assert check_av_trap(decoded, analog)[0] == PASS
    # A binary guess is not an AV-trap candidate.
    assert check_av_trap({"measurement_type": "status"}, _stats())[0] == "N/A"


def test_av_trap_exempts_two_valued_setpoints():
    # A day/night setpoint (e.g. 50/120 Pa) legitimately holds two values.
    decoded = {"measurement_type": "trykk", "object_type": "AV",
               "function": "settpunkt"}
    two_valued = _stats(values=[50.0, 120.0])
    verdict, evidence = check_av_trap(decoded, two_valued)
    assert verdict == PASS and "day/night" in evidence


def test_av_trap_confirms_corrected_av_as_binary_decode():
    # A decode that already declares the AV object binary (measurement_type
    # status) must be CONFIRMED by 2-valued data, not re-flagged.
    decoded = {"measurement_type": "status", "object_type": "AV",
               "function": "status (binaer verdi)"}
    verdict, evidence = check_av_trap(decoded, _stats())
    assert verdict == PASS and "known AV-as-binary" in evidence


def test_range_checks():
    temp_ok = _stats(min=18.0, max=24.5, distinct_count=None, distinct_capped=True)
    assert check_range({"measurement_type": "temperatur"}, temp_ok)[0] == PASS
    temp_bad = _stats(min=-80.0, max=500.0)
    assert check_range({"measurement_type": "temperatur"}, temp_bad)[0] == CONFLICT
    co2_ok = _stats(min=350.0, max=1800.0)
    assert check_range({"measurement_type": "co2"}, co2_ok)[0] == PASS
    ao = {"object_type": "AO", "measurement_type": "kommando"}
    assert check_range(ao, _stats(min=0.0, max=87.5))[0] == PASS
    assert check_range(ao, _stats(min=-5.0, max=140.0))[0] == CONFLICT
    # trykk: unit unknown -> evidence only, never a verdict either way.
    assert check_range({"measurement_type": "trykk"}, _stats())[0] == INCONCLUSIVE
    # status has no range check.
    assert check_range({"measurement_type": "status"}, _stats())[0] == "N/A"


def test_dead_point():
    dead = _stats(distinct_count=1, values=[1.0])
    verdict, evidence = check_dead_point({}, dead)
    assert verdict == INCONCLUSIVE and "constant" in evidence
    assert check_dead_point({}, _stats())[0] == PASS
    assert check_dead_point({}, _stats(n_num=0))[0] == INCONCLUSIVE


def test_dead_point_constant_is_expected_for_setpoints_and_quiet_alarms():
    const_90 = _stats(distinct_count=1, values=[90.0])
    const_0 = _stats(distinct_count=1, values=[0.0])
    const_1 = _stats(distinct_count=1, values=[1.0])
    # A never-adjusted setpoint is normal (Norwegian free text, any casing).
    verdict, evidence = check_dead_point({"function": "Settpunkt"}, const_90)
    assert verdict == PASS and "setpoint" in evidence
    # An alarm that never fired is normal ...
    assert check_dead_point({"function": "alarm"}, const_0)[0] == PASS
    # ... but a constantly-ACTIVE alarm is suspicious.
    assert check_dead_point({"function": "alarm"}, const_1)[0] == INCONCLUSIVE
    # A constant plain status point stays inconclusive.
    assert check_dead_point({"function": "status"}, const_1)[0] == INCONCLUSIVE


def test_energy_monotonic():
    decoded = {"measurement_type": "energi"}
    assert check_energy_monotonic(decoded, _stats(monotonic_nondecreasing=True))[0] == PASS
    assert check_energy_monotonic(decoded, _stats(monotonic_nondecreasing=False))[0] == CONFLICT
    assert check_energy_monotonic(decoded, _stats(monotonic_nondecreasing=None))[0] == INCONCLUSIVE
    assert check_energy_monotonic({"measurement_type": "status"}, _stats())[0] == "N/A"


def test_file_kind():
    assert check_file_kind({"object_type": "BI"}, _stats(file_kinds=["BV"]))[0] == PASS
    assert check_file_kind({"object_type": "BI"}, _stats(file_kinds=["AV"]))[0] == CONFLICT
    assert check_file_kind({"object_type": "AI"}, _stats(file_kinds=["BV"]))[0] == CONFLICT
    assert check_file_kind({"object_type": "AI"}, _stats(file_kinds=["AV", "BV"]))[0] == INCONCLUSIVE
    assert check_file_kind({"object_type": None}, _stats())[0] == "N/A"
    assert check_file_kind({"object_type": "MV"}, _stats(file_kinds=["AV"]))[0] == "N/A"
    assert check_file_kind({"object_type": "AI"}, _stats(file_kinds=[]))[0] == "N/A"


# --- end to end ---------------------------------------------------------------

def _decoded(label, **over):
    base = {
        "raw_label": label, "source_type": "bacnet", "confidence": 0.5,
        "validated": False, "measurement_type": "status", "object_type": "BI",
        "relationships": [],
    }
    base.update(over)
    return base


def test_cross_check_join_and_data_checks():
    outputs = [
        _decoded("known"),
        _decoded("unknown-label"),
    ]
    stats_rows = [_stats(raw_label="known", file_kinds=["BV"])]
    checked, missing = cross_check(outputs, stats_rows)
    assert missing == ["unknown-label"]
    assert len(checked) == 1
    dc = checked[0]["data_checks"]
    assert dc["distinct_values"] == 2
    assert dc["monotonic"] is False
    assert dc["temp_correlation"] is None
    assert dc["conflict"] is False   # binary guess, binary data, BV file


def test_conflict_flag_set_on_any_conflict():
    decoded = _decoded("L", measurement_type="temperatur", object_type="AV")
    results = run_checks(decoded, _stats())  # 2-valued analog guess -> AV trap
    dc = build_data_checks(_stats(), results)
    assert dc["conflict"] is True


def test_augmented_row_stays_schema_valid():
    validator = build_validator()
    decoded = _decoded("L")
    results = run_checks(decoded, _stats(file_kinds=["BV"]))
    decoded_with = dict(decoded)
    decoded_with["data_checks"] = build_data_checks(_stats(), results)
    assert validate_instance(decoded_with, validator) == []
