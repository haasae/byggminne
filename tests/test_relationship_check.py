from src.profile.relationship_check import (
    CONFLICT,
    NO_SIGNAL,
    PASS,
    SKIPPED,
    SUPPORTED,
    build_groups,
    build_relationships,
    co_behavior_check,
    directional_check,
    group_keys,
    point_role,
    tur_retur_check,
)
from src.validate.schema_validator import build_validator, validate_instance

FCB_RT = "A20-P2-APP019:20053401-OU001/FCB.Local Application.-RT401.#85"
FCB_RD = "A20-P2-APP019:20053401-OU001/FCB.Local Application.-RD401.#85"
N2_RT4 = "A20-P2-APP019:NIE00108D0A91DD/N2 Trunk 1.320001.Analoge innganger.RT401.#85"
N2_RT5 = "A20-P2-APP019:NIE00108D0A91DD/N2 Trunk 1.320001.Analoge innganger.RT507.#85"
N2_BYGG = "A20-P2-APP019:NIE00108D0A91DD/N2 Trunk 1.320001_bygg5.kj maskin bygg5etg3.BI3.#85"
PUMP = "A20-P2-APP019:20053404-OU002/FCB.Local Application.Spillvannspumpe_P2.-P2_Drift.#85"
IK = "A20-P2-APP019:NIE00108D0A91DD/ModbusRTU2.IK001_TEST.Arb_Spkt.#85"


# --- structural grouping -------------------------------------------------------

def test_group_keys_controller_system_equipment():
    assert ("same_controller", "20053401-OU001") in group_keys(FCB_RT)
    assert ("same_system", "320001") in group_keys(N2_RT4)
    assert ("same_system", "320001_bygg5") in group_keys(N2_BYGG)
    assert ("same_equipment", "Spillvannspumpe_P2") in group_keys(PUMP)
    assert ("same_equipment", "IK001_TEST") in group_keys(IK)
    # The N2 path has no controller segment and no equipment token.
    kinds = {kind for kind, _ in group_keys(N2_RT4)}
    assert "same_controller" not in kinds


def test_point_role_reads_component_side():
    assert point_role(FCB_RT) == ("RT", "4")
    assert point_role(N2_RT5) == ("RT", "5")
    assert point_role(IK) == (None, None)     # no NN-digit point code


def test_build_groups_and_relationships():
    outputs = [{"raw_label": l} for l in (FCB_RT, FCB_RD, N2_RT4, N2_RT5, PUMP)]
    groups = build_groups(outputs)
    assert set(groups[("same_controller", "20053401-OU001")]) == {FCB_RT, FCB_RD}
    assert set(groups[("same_system", "320001")]) == {N2_RT4, N2_RT5}
    # A single-member group (the pump) defines no relationships.
    assert ("same_equipment", "Spillvannspumpe_P2") not in groups

    rel = build_relationships(groups)
    assert {"type": "same_controller", "target_raw_label": FCB_RD} in rel[FCB_RT]
    assert {"type": "same_system", "target_raw_label": N2_RT4} in rel[N2_RT5]


# --- data verification ----------------------------------------------------------

def _series(values, start_hour=0):
    return {f"2025-01-01 {start_hour + i:02d}:00:00.000": v for i, v in enumerate(values)}


def _stats(**over):
    base = {"distinct_count": 10, "is_binary": False}
    base.update(over)
    return base


def test_directional_heating_pass_and_conflict():
    outdoor = _series([-5.0, 0.0, 5.0, 10.0, 15.0, 20.0])
    supply = _series([60.0, 50.0, 40.0, 35.0, 30.0, 25.0])   # anti-correlated
    decoded = {"raw_label": "x", "primary_system": {"code": "3200"}, "function": "temperatur"}
    result = directional_check(decoded, _stats(), supply, outdoor)
    assert result["verdict"] == PASS
    # The same series against a COOLING claim must conflict.
    cooled = dict(decoded, primary_system={"code": "3700"})
    assert directional_check(cooled, _stats(), supply, outdoor)["verdict"] == CONFLICT


def test_directional_skips_setpoints_constants_binaries_and_other_systems():
    outdoor = _series([1.0, 2.0, 3.0])
    member = _series([3.0, 2.0, 1.0])
    setpoint = {"primary_system": {"code": "3200"}, "function": "settpunkt"}
    assert directional_check(setpoint, _stats(), member, outdoor)["verdict"] == SKIPPED
    plain = {"primary_system": {"code": "3200"}, "function": "temperatur"}
    assert directional_check(plain, _stats(distinct_count=1), member, outdoor)["verdict"] == SKIPPED
    assert directional_check(plain, _stats(is_binary=True), member, outdoor)["verdict"] == SKIPPED
    sanitary = {"primary_system": {"code": "3100"}, "function": "status"}
    assert directional_check(sanitary, _stats(), member, outdoor) is None


def test_directional_skips_commands_but_records_correlation():
    # A reverse-acting valve legitimately correlates POSITIVELY with outdoor
    # on a heating system -- commands must not be judged, only recorded.
    outdoor = _series([-5.0, 0.0, 5.0, 10.0])
    valve = _series([10.0, 30.0, 60.0, 90.0])   # opens in warm weather
    decoded = {"primary_system": {"code": "3200"}, "measurement_type": "kommando",
               "function": "paadrag"}
    result = directional_check(decoded, _stats(), valve, outdoor)
    assert result["verdict"] == SKIPPED
    assert "actuator-direction-specific" in result["evidence"]
    assert "r=+" in result["evidence"]


def test_tur_retur_ordering():
    tur = _series([60.0, 55.0, 50.0, 45.0])
    retur = _series([40.0, 38.0, 36.0, 35.0])
    assert tur_retur_check("a", tur, "b", retur)["verdict"] == PASS
    # Swapped roles: "tur" mostly BELOW "retur" -> contradiction.
    assert tur_retur_check("a", retur, "b", tur)["verdict"] == CONFLICT
    # No aligned samples -> skipped.
    assert tur_retur_check("a", tur, "b", _series([1.0], start_hour=20))["verdict"] == SKIPPED


def test_co_behavior_supported_and_no_signal():
    x = _series([1.0, 2.0, 3.0, 4.0])
    y = _series([2.0, 4.0, 6.0, 8.0])
    assert co_behavior_check(x, y)["verdict"] == SUPPORTED
    # A symmetric wiggle with exactly zero correlation to the ramp.
    z = _series([1.0, -1.0, -1.0, 1.0])
    assert co_behavior_check(x, z)["verdict"] == NO_SIGNAL
    const = _series([5.0, 5.0, 5.0, 5.0])
    assert co_behavior_check(x, const)["verdict"] == SKIPPED


def test_relationships_keep_augmented_rows_schema_valid():
    validator = build_validator()
    row = {
        "raw_label": FCB_RT, "source_type": "bacnet", "confidence": 0.5,
        "validated": False,
        "relationships": [{"type": "same_controller", "target_raw_label": FCB_RD}],
    }
    assert validate_instance(row, validator) == []
