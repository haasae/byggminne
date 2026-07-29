"""Tests for src.heating.flexibility."""
import json
from pathlib import Path

from src.heating.flexibility import rank_zones, render


def _make_data():
    ht = {
        ("B90", "Z1"): {"verdict": "electric-fast", "confidence": 0.8},
        ("B90", "Z2"): {"verdict": "floor-slow", "confidence": 0.6},
        ("B90", "Z3"): {"verdict": "excluded", "confidence": 0.5},
        ("B90", "Z4"): {"verdict": "ambiguous", "confidence": 0.3},
    }
    tau = {
        ("B90", "Z1"): {"minutes_to_1k": {"median": 45, "iqr": 5}},
        ("B90", "Z2"): {"minutes_to_1k": {"median": 240, "iqr": 60}},
    }
    orient = {
        ("B90", "Z1"): {"orientation": "heating", "winter_duty": 70.0, "summer_duty": 5.0},
        ("B90", "Z2"): {"orientation": "heating", "winter_duty": 50.0, "summer_duty": 3.0},
        ("B90", "Z3"): {"orientation": "cooling", "winter_duty": 2.0, "summer_duty": 80.0},
    }
    return ht, tau, orient


def test_rank_zones_order():
    ht, tau, orient = _make_data()
    rows = rank_zones(ht, tau, orient)
    verdicts = [r["verdict"] for r in rows]
    # electric-fast before floor-slow before ambiguous before excluded
    assert verdicts.index("electric-fast") < verdicts.index("floor-slow")
    assert verdicts.index("floor-slow") < verdicts.index("ambiguous")
    assert verdicts.index("ambiguous") < verdicts.index("excluded")


def test_rank_zones_headroom():
    ht, tau, orient = _make_data()
    rows = rank_zones(ht, tau, orient)
    z1 = next(r for r in rows if r["zone"] == "Z1")
    assert abs(z1["headroom_pct"] - 30.0) < 1e-6


def test_render_produces_markdown(tmp_path):
    ht, tau, orient = _make_data()
    rows = rank_zones(ht, tau, orient)
    out = tmp_path / "flex.md"
    n = render(rows, out)
    assert n == 4
    text = out.read_text(encoding="utf-8")
    assert "# Flexibility map" in text
    assert "electric-fast" in text.lower() or "Fast electric" in text
    assert "Z1" in text
