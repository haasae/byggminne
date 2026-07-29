"""Regime classification: survey-shaped cases + threshold edges."""
from pathlib import Path

from src.common.io_utils import read_json
from src.heating.gain_regime import classify

RULES = read_json(Path(__file__).parents[1] / "knowledge_base" / "heating_rules.json")


def zrow(pct0=0.0, pct100=0.0, interior=0.0, distinct=10, top=None,
         n=10000, flags=(), n_data=10000):
    return {
        "flags": list(flags),
        "stats": {
            "n_data": n_data,
            "gain": {
                "n": n, "pct_at_0": pct0, "pct_at_100": pct100,
                "pct_interior": interior, "distinct": distinct,
                "top_values": top or [],
            },
        },
    }


def test_binary_pure():
    regime, why = classify(zrow(pct0=0.6, pct100=0.39), RULES)
    assert regime == "binary" and "0/100" in why


def test_binary_with_kn_resampling_averages():
    # 95% at 0/100 + 4% on 50/33.33 -- the resampled on/off signature.
    top = [{"value": 50.0, "count": 300}, {"value": 33.333333, "count": 100}]
    regime, _ = classify(zrow(pct0=0.5, pct100=0.45, interior=0.05,
                              distinct=20, top=top), RULES)
    assert regime == "binary"


def test_modulating_b01_shape():
    # B01-MA-A-1-21: ~63% interior, ~2000 distinct, saturates at 99 not 100.
    regime, _ = classify(zrow(pct0=0.3, pct100=0.0, interior=0.63,
                              distinct=2000), RULES)
    assert regime == "modulating"


def test_modulating_when_distinct_capped():
    regime, _ = classify(zrow(pct0=0.4, pct100=0.1, interior=0.5,
                              distinct=None), RULES)
    assert regime == "modulating"


def test_mixed_middle():
    regime, _ = classify(zrow(pct0=0.85, pct100=0.05, interior=0.1,
                              distinct=40), RULES)
    assert regime == "mixed"


def test_dead_and_no_data():
    assert classify(zrow(flags=["dead_gain"]), RULES)[0] == "dead"
    assert classify(zrow(flags=["empty"], n_data=0), RULES)[0] == "no_data"
    assert classify(zrow(n=0), RULES)[0] == "no_data"
