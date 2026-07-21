from src.common.io_utils import read_jsonl
from src.decode.enrichment import run, select

# Two structural siblings (digits differ, letters same) missing point
# semantics, one complete row, one building-gap-only row.
THIN_A = "SITE:111-OU001/-XQ401.#1"
THIN_B = "SITE:222-OU001/-XQ402.#1"


def _row(raw_label, **over):
    row = {
        "raw_label": raw_label, "source_type": "bacnet",
        "primary_system": {"code": "3200", "description": "Varme"},
        "measurement_type": "temperatur", "function": "temperatur",
        "location": {"building": "111", "zone": None},
        "confidence": 0.65, "decode_method": "rules",
    }
    row.update(over)
    return row


def _rows():
    return [
        _row(THIN_B, measurement_type=None, function=None),
        _row(THIN_A, measurement_type=None, function=None),
        _row("SITE:111-OU001/-RT401.#1"),                      # complete
        _row("NIE/x.floating point", location=None),           # building gap only
    ]


def test_family_dedupe_picks_lexicographic_representative():
    residue, manifest = select(_rows())
    assert [r["raw_label"] for r in residue] == [THIN_A]       # A < B
    assert manifest[0]["family_size"] == 2
    assert manifest[0]["selected_for"] == ["point_semantics"]
    assert set(residue[0]) == {"raw_label", "source_type"}     # input-shaped


def test_building_only_gap_is_never_selected():
    labels = {m["raw_label"] for _, m in [(None, m) for m in select(_rows())[1]]}
    assert "NIE/x.floating point" not in labels


def test_full_mode_selects_every_gapped_row():
    residue, _ = select(_rows(), dedupe_families=False)
    assert {r["raw_label"] for r in residue} == {THIN_A, THIN_B}


def test_run_writes_artifacts(tmp_path):
    outputs = tmp_path / "outputs.jsonl"
    import json
    outputs.write_text("\n".join(json.dumps(r) for r in _rows()),
                       encoding="utf-8")
    residue, manifest = run(outputs, tmp_path / "enrich")
    assert (tmp_path / "enrich" / "enrichment_residue.jsonl").exists()
    assert read_jsonl(tmp_path / "enrich" / "enrichment_residue.jsonl") == residue
    report = (tmp_path / "enrich" / "enrichment_report.md").read_text(encoding="utf-8")
    assert "not selectable" in report          # building gap stays visible
    assert "/enrich" in report
