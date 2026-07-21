from src.decode.rules_engine import FULL, NONE, PARTIAL, decode_rules
from src.validate.schema_validator import build_validator, validate_instance


def _decode(label, source_type="bacnet"):
    return decode_rules(label, source_type)


def test_fcb_component_label():
    instance, tier = _decode(
        "A20-P2-APP019:20053401-OU001/FCB.Local Application.-RT401.#85")
    assert tier == FULL
    assert instance["component"].startswith("RT401 (RT = Temperaturgiver")
    assert instance["measurement_type"] == "temperatur"
    assert instance["subsystem"] == "tur/tilluft (supply)"
    assert instance["location"] == {"building": "20053401", "zone": None}
    assert "komponentkodeliste.md" in instance["reasoning"]
    assert "tasen" in instance["reasoning"]  # area via control_number_area_map


def test_n2_system_label_full_house():
    instance, tier = _decode(
        "A20-P2-APP019:NIE00108D0A91DD/N2 Trunk 1.320001.Analoge innganger.RT401.#85")
    assert tier == FULL
    assert instance["primary_system"] == {"code": "3200", "description": "Varmeanlegg"}
    assert instance["object_type"] == "AI"
    assert "system 320.001" in instance["subsystem"]
    assert instance["confidence"] >= 0.85


def test_legacy_code_always_output_as_4_digit():
    for label in (
        "A20-P2-APP019:NIE00108D0A91DD/N2 Trunk 1.320001.Analoge utganger.SB41.#85",
        "A20-P2-APP019:NIE00108D0A91DD/N2 Trunk 1.320001_bygg3.Analoge innganger.RT401.#85",
        "A20-P2-APP019:NIE00108D0A91DD/N2 Trunk 1.320001_bygg5.kj maskin bygg5etg3.BI3.#85",
    ):
        instance, _ = _decode(label)
        assert instance["primary_system"]["code"] == "3200", label


def test_bygg_token_wins_building_and_bo_command():
    instance, tier = _decode(
        "A20-P2-APP019:NIE00108D0A91DD/N2 Trunk 1.320001_bygg5.kj maskin bygg5etg3.BO1.#85")
    assert instance["location"]["building"] == "bygg5"
    assert instance["object_type"] == "BO"
    assert instance["measurement_type"] == "kommando"


def test_pump_alarm_label():
    instance, tier = _decode(
        "A20-P2-APP019:20053404-OU002/FCB.Local Application."
        "Spillvannspumpe_P2.-P2_Alarm_Høy_vannstand.#85")
    assert tier == FULL
    assert instance["function"] == "alarm"
    assert instance["measurement_type"] == "status"
    assert instance["carrier"] == "vann"
    assert instance["component"] == "spillvannspumpe (pumpe)"
    assert instance["location"]["building"] == "20053404"


def test_ik_equipment_and_cooling_keywords():
    instance, tier = _decode(
        "A20-P2-APP019:NIE00108D0A91DD/ModbusRTU2.IK001_TEST.Kjole_Drift-.#85")
    assert tier == FULL
    assert instance["component"].startswith("IK001 (IK = Kuldeaggregat")
    assert instance["carrier"] == "kjoling"
    assert instance["measurement_type"] == "status"
    assert "_TEST" in instance["reasoning"]


def test_wsp_suffix_redefines_role_to_setpoint():
    instance, _ = _decode(
        "A20-P2-APP019:20053402-OU007/FCB.Local Application.-RT404_WSP.#85")
    assert instance["function"] == "settpunkt"
    assert instance["measurement_type"] == "temperatur"   # RT -> temperature setpoint
    assert instance["component"].startswith("RT404")


def test_modbus_temperature_and_co2():
    t, _ = _decode("A20-P2-APP019:NIE00108D0A91DD/ModbusRTU2.1031_adr10.Temperature.#85")
    assert t["measurement_type"] == "temperatur"
    c, _ = _decode("A20-P2-APP019:NIE00108D0A91DD/ModbusRTU2.1031_adr10.CO2.#85")
    assert c["measurement_type"] == "co2" and c["unit"] == "ppm"


def test_heating_keyword_gives_system_hint():
    instance, _ = _decode(
        "A20-P2-APP019:NIE00108D0A91DD/ModbusRTU.2017_adr1.Heating control  connector A2.#85")
    assert instance["primary_system"]["code"] == "3200"
    assert "text hint" in instance["reasoning"]


SWEGON = "A20-P2-APP019:20056703-Skoyen/BACnet IP1.Swegon Wise.Analoge verdier."


def test_swegon_room_comfort_setpoints():
    h, tier = _decode(SWEGON + "Rom 1-03 H Temp Occ.#85")
    assert tier == FULL
    assert h["primary_system"]["code"] == "3600"       # Swegon Wise -> ventilation
    assert h["function"].startswith("settpunkt (varme")
    assert h["measurement_type"] == "temperatur"
    assert h["location"]["zone"] == "Rom 1-03"
    assert h["location"]["building"] == "20056703"
    assert h["object_type"] == "AV"

    c, _ = _decode(SWEGON + "Rom 1-03 C Temp Uocc.#85")
    assert c["carrier"] == "kjoling"
    assert c["function"].startswith("settpunkt (kjoling")

    natt, _ = _decode(SWEGON + "Rom 1-03 Temp natt.#85")
    assert natt["function"] == "settpunkt (nattsenking)"


def test_swegon_flow_and_vav_setpoints():
    flow, tier = _decode(SWEGON + "Rom 1-03 Flow Min Setp.#85")
    assert tier == FULL
    assert flow["measurement_type"] == "volum"
    assert flow["function"] == "settpunkt"
    vav, _ = _decode(SWEGON + "Rom 1-03 VAV Max Setp.#85")
    assert vav["measurement_type"] == "volum"
    slave, _ = _decode(SWEGON + "Rom 1-03 Flow Max Slave.#85")
    assert slave["measurement_type"] == "volum"
    assert slave["function"].startswith("grenseverdi")


def test_swegon_bare_ai_point_is_partial_not_residue():
    instance, tier = _decode(
        "A20-P2-APP019:20056703-Skoyen/BACnet IP1.Swegon Wise.Analoge innganger.AI-1128.#85")
    assert tier == PARTIAL
    assert instance["object_type"] == "AI"
    assert instance["primary_system"]["code"] == "3600"
    assert instance["confidence"] >= 0.4               # decoded, not residue
    assert instance["function"] is None                # nothing invented


def test_skoyen_sk_system_and_combined_subsystem_component():
    instance, tier = _decode(
        "A20-P2-APP019:20056703-Skoyen/BACnet IP1.SK320001.Utganger.313_001_SB401.#85")
    assert instance["primary_system"]["code"] == "3200"   # SK320001
    assert "313.001" in instance["subsystem"]
    assert instance["component"].startswith("SB401 (SB = Reguleringsventil")
    # Honest PARTIAL: bare 'Utganger' does not fix analog-vs-binary, so
    # function/measurement stay null rather than guessed.
    assert tier == PARTIAL
    assert instance["function"] is None


def test_energy_meter_keywords_fjernvarme_and_hovedtavle():
    fv, tier = _decode(
        "A20-P2-APP019:20056701-Skoyen/BACnet IP1.320001.Innganger."
        "WM01_Energi_Fjernvarme.Totalisering1.#85")
    assert fv["carrier"] == "fjernvarme"
    assert fv["measurement_type"] == "energi"
    assert fv["function"] == "energimaaling"
    assert tier == FULL

    el, _ = _decode(
        "A20-P2-APP019:20056701-Skoyen/BACnet IP1.320001.Innganger."
        "WM02_Energi_Hovedtavle.Totalisering1.#85")
    assert el["carrier"] == "el"
    assert el["measurement_type"] == "energi"


def test_cooling_system_token_infers_carrier():
    instance, _ = _decode(
        "A20-P2-APP019:NIE00108D0A91DD/N2 Trunk 1.370001.Analoge innganger.RT401.#85")
    assert instance["primary_system"]["code"] == "3700"
    assert instance["carrier"] == "kjoling"
    assert "system_carrier" in instance["reasoning"]


def test_heating_system_never_infers_carrier():
    instance, _ = _decode(
        "A20-P2-APP019:NIE00108D0A91DD/N2 Trunk 1.320001.Analoge innganger.RT401.#85")
    # 32xx heating carrier is el OR fjernvarme -- must stay null without evidence.
    assert instance["carrier"] is None


def test_bygg_etg_token_fills_zone():
    instance, _ = _decode(
        "A20-P2-APP019:NIE00108D0A91DD/N2 Trunk 1.320001_bygg5.kj maskin bygg5etg3.BO1.#85")
    assert instance["location"] == {"building": "bygg5", "zone": "etg3"}

    standalone, _ = _decode(
        "A20-P2-APP019:NIE00108D0A91DD/ModbusRTU2.IK001_TEST.Kjolemaskin bygg2etg1 Drift.#85")
    assert standalone["location"] == {"building": "bygg2", "zone": "etg1"}


def test_unknown_label_is_none_tier_never_invents():
    instance, tier = _decode("Completely/Unknown.Format.XYZ")
    assert tier == NONE
    assert instance["primary_system"] is None
    assert instance["component"] is None
    assert instance["confidence"] <= 0.4


def test_all_family_exemplars_schema_valid():
    validator = build_validator()
    labels = [
        "A20-P2-APP019:20053401-OU001/FCB.Local Application.-RT401.#85",
        "A20-P2-APP019:20053401-OU001/FCB.Local Application.-RD401.#85",
        "A20-P2-APP019:20053401-OU001/FCB.Local Application.-LR401.#85",
        "A20-P2-APP019:20053401-OU001/FCB.Local Application.-SB401.#85",
        "A20-P2-APP019:20053402-OU007/FCB.Local Application.-RP401_SP.#85",
        "A20-P2-APP019:NIE00108D0A91DD/ModbusRTU2.320x_adr106.Effective Set point.#85",
        "A20-P2-APP019:NIE00108D0A91DD/ModbusRTU2.IK001_TEST.Arb_Spkt.#85",
        "A20-P2-APP019:20053404-OU001/FCB.Local Application.Drenspumpe_P1.-P1_Drift.#85",
        "A20-P2-APP019:NIE00108D0A91DD/N2 Trunk 1.320001.Analoge innganger.RT507.#85",
        "A20-P2-APP019:NIE00108D0A91DD/ModbusRTU.21xx_adr23.Heating control  connector A2.#85",
    ]
    for label in labels:
        instance, _tier = decode_rules(label, "bacnet")
        assert validate_instance(instance, validator) == [], label
