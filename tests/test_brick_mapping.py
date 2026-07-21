import json

import pytest

from src.brick.mapping import (
    component_letters,
    equipment_class,
    mapped_class_names,
    point_class,
    system_class,
    unit_iri,
)
from src.common.io_utils import repo_root


def test_rule_order_setpoint_beats_sensor():
    row = {"function": "settpunkt (varme, tilstede)",
           "measurement_type": "temperatur"}
    cls, citation = point_class(row)
    assert cls == "Temperature_Setpoint"
    assert "brick_mapping.json:point_class_rules" in citation

    sensor = {"function": "temperatur", "measurement_type": "temperatur",
              "component": "RT401 (RT = Temperaturgiver)"}
    assert point_class(sensor)[0] == "Temperature_Sensor"


def test_rd_maps_to_differential_pressure():
    row = {"measurement_type": "trykk", "component": "RD401 (RD = Differansetrykkgiver)"}
    assert point_class(row)[0] == "Differential_Pressure_Sensor"
    rp = {"measurement_type": "trykk", "component": "RP401 (RP = Trykkgiver)"}
    assert point_class(rp)[0] == "Pressure_Sensor"


def test_unknown_row_falls_back_to_point_never_invents():
    cls, citation = point_class({"function": None, "measurement_type": None})
    assert cls == "Point"
    assert "fallback" in citation


def test_equipment_classes_ik_stays_generic():
    assert equipment_class("LR401")[0] == "Variable_Frequency_Drive"
    assert equipment_class("Spillvannspumpe_P2")[0] == "Pump"
    assert equipment_class("IK001_TEST")[0] == "Equipment"   # NOT Chiller
    assert equipment_class("ModbusRTU2.2017_adr1")[0] == "Equipment"


def test_system_classes():
    assert system_class("3200")[0] == "Hot_Water_System"
    assert system_class("3700")[0] == "Chilled_Water_System"
    assert system_class("9999")[0] == "System"               # unknown prefix
    assert system_class(None)[0] == "System"


def test_unit_map():
    iri, _ = unit_iri("°C")
    assert iri == "http://qudt.org/vocab/unit/DEG_C"
    assert unit_iri("NOK") == (None, None)
    assert unit_iri(None) == (None, None)


def test_component_letters():
    assert component_letters("RT401 (RT = Temperaturgiver)") == "RT"
    assert component_letters("spillvannspumpe (pumpe)") is None
    assert component_letters(None) is None


def test_every_entry_cites_a_source():
    mapping = json.loads(
        (repo_root() / "knowledge_base/brick_mapping.json").read_text(encoding="utf-8"))
    for section in ("system_prefix_class", "equipment_letter_class",
                    "equipment_token_class", "unit_map"):
        for key, entry in mapping[section].items():
            if key.startswith("_"):
                continue
            assert "_source" in entry, f"{section}.{key} lacks _source"
    for rule in mapping["point_class_rules"]:
        if "class" in rule:
            assert "_source" in rule, f"point rule {rule['class']} lacks _source"


def test_all_mapped_classes_exist_in_brick():
    class_list = repo_root() / "knowledge_base/brick_dir/brick_classes.txt"
    if not class_list.exists():
        pytest.skip("brick_classes.txt not built yet -- download Brick.ttl and run "
                    "python -m src.brick.build_class_list (round incomplete until then)")
    official = set(class_list.read_text(encoding="utf-8").split())
    for name in mapped_class_names():
        assert name in official, f"'{name}' is not a Brick class"
