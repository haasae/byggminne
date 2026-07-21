import json

import pytest

from src.decode import retrieval
from src.decode.retrieval import inherit_fields, point_name, retrieve, signature

RT401_OU1 = "A20-P2-APP019:20053401-OU001/FCB.Local Application.-RT401.#85"
RT401_OU2 = "A20-P2-APP019:20053401-OU002/FCB.Local Application.-RT401.#85"
RT402_OU1 = "A20-P2-APP019:20053401-OU001/FCB.Local Application.-RT402.#85"
RD401_OU1 = "A20-P2-APP019:20053401-OU001/FCB.Local Application.-RD401.#85"


@pytest.fixture(autouse=True)
def _fresh_cache():
    retrieval.clear_cache()
    yield
    retrieval.clear_cache()


def _write_store(tmp_path, rows):
    p = tmp_path / "store.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                 encoding="utf-8")
    return str(p)


def _gold_rt401():
    return {
        "raw_label": RT401_OU1, "source_type": "bacnet",
        "function": "utetemperatur (outdoor temperature)",
        "measurement_type": "temperatur", "unit": "°C",
        "subsystem": None, "component": "RT401 (RT = Temperaturgiver)",
        "primary_system": None, "carrier": None, "is_derived": False,
        "confidence": 1.0, "validated": True,
    }


def test_signature_parameterizes_digits_only():
    assert signature(RT401_OU1) == signature(RT401_OU2)   # other OU
    assert signature(RT401_OU1) == signature(RT402_OU1)   # other lopenummer
    assert signature(RT401_OU1) != signature(RD401_OU1)   # other component letters


def test_exact_hit_returns_stored_row(tmp_path):
    store = _write_store(tmp_path, [_gold_rt401()])
    kind, row = retrieve(RT401_OU1, store)
    assert kind == "exact"
    assert row["function"].startswith("utetemperatur")


def test_sibling_never_transfers_observation_fields_even_same_name(tmp_path):
    # RT401 on another OU shares the name, but only OU001's was data-verified
    # as outdoor -- observations stay with their exact label (Skoyen lesson:
    # RD503 on another system shared a name yet was genuinely analog).
    store = _write_store(tmp_path, [_gold_rt401()])
    kind, row = retrieve(RT401_OU2, store)
    assert kind == "sibling"
    donations = inherit_fields(row, RT401_OU2)
    assert "function" not in donations
    assert "unit" not in donations
    assert donations["component"][0].startswith("RT401")   # structural OK


def test_rt402_does_not_inherit_outdoor_the_rt401_trap(tmp_path):
    store = _write_store(tmp_path, [_gold_rt401()])
    kind, row = retrieve(RT402_OU1, store)
    assert kind == "sibling"                       # structurally identical
    donations = inherit_fields(row, RT402_OU1)
    # Observation-derived fields must NOT cross labels.
    assert "function" not in donations
    assert "unit" not in donations
    assert "measurement_type" not in donations
    assert donations["component"][0].startswith("RT401")   # structural donation
    assert "structural fields only" in donations["component"][1]


def test_binary_correction_does_not_leak_to_other_av_points(tmp_path):
    # The Skoyen regression: 'AV-0 is semantically binary' is an observation
    # about AV-0; AV-33 (same signature, different name) must not inherit it.
    av0 = "X:20056703-Skoyen/BACnet IP1.360001.Analoge verdier.AV-0.#85"
    av33 = "X:20056703-Skoyen/BACnet IP1.360001.Analoge verdier.AV-33.#85"
    store = _write_store(tmp_path, [{
        "raw_label": av0, "source_type": "bacnet", "measurement_type": "status",
        "function": "status (binaer verdi paa analog-typet objekt)",
        "object_type": "AV", "confidence": 0.9, "validated": True,
    }])
    kind, row = retrieve(av33, store)
    assert kind == "sibling"
    donations = inherit_fields(row, av33)
    assert "measurement_type" not in donations
    assert "function" not in donations
    assert donations["object_type"][0] == "AV"     # structure still transfers


def test_point_name_and_missing_store(tmp_path):
    assert point_name(RT401_OU1) == "-RT401"
    assert retrieve(RT401_OU1, str(tmp_path / "absent.jsonl")) is None
