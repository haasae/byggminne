import json

from src.eval.token_probe import CODE_LIKE, MUTATIONS, probe, render


def test_probe_reports_missed_code_and_unrecognized(tmp_path):
    batch = tmp_path / "input.jsonl"
    rows = [
        # decodes fully (component from point code)
        {"raw_label": "A:20053401-OU001/FCB.Local Application.-RT401.#85",
         "source_type": "bacnet"},
        # code-like token in an unknown layout -> missed-code candidate
        {"raw_label": "A:B/Weird Vendor.XQ99 gadget zz77.#85", "source_type": "other"},
    ]
    batch.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")

    result = probe([batch])
    assert result["n"] == 2
    assert any("zz77" in codes or "XQ99" in codes
               for _, codes in result["missed_codes"])
    assert any("weird vendor" in sig for sig in result["unrecognized"])
    report = render(result)
    assert "Mutation probe" in report and "Unrecognized segment" in report


def test_mutations_produce_different_labels():
    label = "A:B/BACnet IP1.563002.Utgang.563_H26-SB602.#85"
    for name, fn in MUTATIONS.items():
        mutated = fn(label)
        assert mutated is None or mutated != label, name


def test_code_like_matches_loosely():
    assert CODE_LIKE.findall("563_H26-sb602 and RT401") == ["sb602", "RT401"]
    assert CODE_LIKE.findall("BACnet IP1") == []
