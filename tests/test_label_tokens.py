from src.common.label_tokens import (
    bygg_etg_of,
    controller_of,
    group_keys,
    io_object_type,
    path_segments,
    point_role,
    point_token_of,
    system_token_of,
)

FCB = "A20-P2-APP019:20053401-OU001/FCB.Local Application.-RT401.#85"
FCB_WSP = "A20-P2-APP019:20053402-OU007/FCB.Local Application.-RT404_WSP.#85"
N2 = "A20-P2-APP019:NIE00108D0A91DD/N2 Trunk 1.320001.Analoge innganger.RT401.#85"
N2_BYGG = "A20-P2-APP019:NIE00108D0A91DD/N2 Trunk 1.320001_bygg5.kj maskin bygg5etg3.BI3.#85"
PUMP = "A20-P2-APP019:20053404-OU002/FCB.Local Application.Spillvannspumpe_P2.-P2_Drift.#85"
SB41 = "A20-P2-APP019:NIE00108D0A91DD/N2 Trunk 1.320001.Analoge utganger.SB41.#85"


def test_path_segments_drop_tag_and_node():
    assert path_segments(FCB) == ["FCB", "Local Application", "-RT401"]
    assert path_segments(N2) == ["N2 Trunk 1", "320001", "Analoge innganger", "RT401"]


def test_controller_and_system_token():
    assert controller_of(FCB) == ("20053401", "OU001")
    assert controller_of(N2) == (None, None)
    assert system_token_of(N2) == ("320001", None)
    assert system_token_of(N2_BYGG) == ("320001", "bygg5")
    assert system_token_of(FCB) == (None, None)


def test_point_token_and_suffix():
    assert point_token_of(FCB) == ("-RT401", None)
    assert point_token_of(FCB_WSP) == ("-RT404", "_WSP")
    assert point_token_of(SB41) == ("SB41", None)
    assert point_token_of(N2_BYGG) == ("BI3", None)


def test_point_token_embedded_tail():
    # Skoyen utgang layout: component code at the end of a larger segment.
    sko = "A20-P2-APP019:20056703-Skoyen/BACnet IP1.563002.Utgang.563_H26-SB602.#85"
    assert point_token_of(sko) == ("SB602", None)
    # Separator variants and a setpoint suffix on the embedded code.
    assert point_token_of("A:B/563002.563_H26_SB602.#85") == ("SB602", None)
    assert point_token_of("A:B/563002.563_H26-RT401_SP.#85") == ("RT401", "_SP")
    # No false positives: equipment tokens and free text stay untouched.
    ik = "A20-P2-APP019:NIE00108D0A91DD/ModbusRTU2.IK001_TEST.Drift-.#85"
    assert point_token_of(ik) == (None, None)
    assert point_token_of("A:B/kj maskin bygg5etg3.#85") == (None, None)


def test_point_role_only_for_three_digit_codes():
    assert point_role(FCB) == ("RT", "4")
    # SB41 has two digits -- the side rule is not confirmed for it.
    assert point_role(SB41) == (None, None)


def test_io_object_type_from_path_or_point():
    assert io_object_type(N2) == "AI"
    assert io_object_type(SB41) == "AO"
    assert io_object_type(N2_BYGG) == "BI"
    assert io_object_type(FCB) is None


def test_group_keys_unchanged_shapes():
    assert ("same_controller", "20053401-OU001") in group_keys(FCB)
    assert ("same_system", "320001_bygg5") in group_keys(N2_BYGG)
    assert ("same_equipment", "Spillvannspumpe_P2") in group_keys(PUMP)


def test_bygg_etg_token():
    assert bygg_etg_of(N2_BYGG) == ("bygg5", "etg3")
    assert bygg_etg_of(FCB) == (None, None)
    # `_bygg5` inside a system token belongs to SYSTEM_TOKEN, not BYGG_ETG.
    assert bygg_etg_of("A:B/N2 Trunk 1.320001_bygg5.BI3.#85") == (None, None)


def test_modbus_device_group_key_is_bus_qualified():
    rtu2 = "A20-P2-APP019:NIE00108D0A91DD/ModbusRTU2.2017_adr1.Temperature.#85"
    rtu1 = "A20-P2-APP019:NIE00108D0A91DD/ModbusRTU.2017_adr1.Temperature.#85"
    assert ("same_equipment", "ModbusRTU2.2017_adr1") in group_keys(rtu2)
    assert ("same_equipment", "ModbusRTU.2017_adr1") in group_keys(rtu1)
    # Same address on different buses must stay distinct equipment.
    assert group_keys(rtu2) != group_keys(rtu1)
