"""Copy-paste harness test: export writes prompts + manifest; collect accepts a
valid (fenced) reply, rejects junk and wrong-echo replies with retry prompts,
and concatenates the accepted rows with the deterministic outputs."""
import json

from src.common.io_utils import read_json, read_jsonl, write_jsonl
from src.decode.manual_batch import run_collect, run_export

LABEL_OK = "TEST-BYGG-01:111-OU001/-RT401.#1"
LABEL_UNPARSEABLE = "junk label one"
LABEL_WRONG_ECHO = "junk label two"
LABEL_DET = "TEST-BYGG-02:222-OU001/-LR401.#1"


def _instance(raw_label, **over):
    inst = {
        "raw_label": raw_label,
        "source_type": "bacnet",
        "carrier": None,
        "function": "temperatur",
        "measurement_type": "temperatur",
        "unit": None,
        "object_type": None,
        "primary_system": {"code": "3200", "description": "Varme"},
        "subsystem": None,
        "component": "RT401 (RT = Temperaturgiver)",
        "location": {"building": "111", "zone": None},
        "is_derived": False,
        "confidence": 0.7,
        "reasoning": "test fixture",
        "data_checks": None,
        "relationships": [],
        "validated": False,
    }
    inst.update(over)
    return inst


def test_export_and_collect(tmp_path):
    residue = tmp_path / "residue.jsonl"
    write_jsonl(residue, [
        {"raw_label": LABEL_OK, "source_type": "bacnet"},
        {"raw_label": LABEL_UNPARSEABLE, "source_type": "other"},
        {"raw_label": LABEL_WRONG_ECHO, "source_type": "other"},
    ])
    out = tmp_path / "manual"
    run_export(residue, out)

    assert sorted(p.name for p in (out / "prompts").iterdir()) == [
        "000.txt", "001.txt", "002.txt",
    ]
    assert LABEL_OK in (out / "prompts" / "000.txt").read_text(encoding="utf-8")
    meta = read_json(out / "meta.json")
    assert meta["n"] == 3 and meta["kb_version"]

    # reply 0: valid instance wrapped in fences; reply 1: unparseable prose;
    # reply 2: valid JSON but echoing the wrong label (saved as .json)
    (out / "replies" / "000.txt").write_text(
        "```json\n" + json.dumps(_instance(LABEL_OK)) + "\n```", encoding="utf-8"
    )
    (out / "replies" / "001.txt").write_text("Sorry, I cannot help.", encoding="utf-8")
    (out / "replies" / "002.json").write_text(
        json.dumps(_instance("some other label")), encoding="utf-8"
    )

    det = tmp_path / "outputs.jsonl"
    write_jsonl(det, [_instance(LABEL_DET)])
    combined = tmp_path / "outputs_full.jsonl"
    run_collect(out, deterministic=det, out=combined)

    llm = read_jsonl(out / "outputs_llm.jsonl")
    assert [r["raw_label"] for r in llm] == [LABEL_OK]
    assert llm[0]["decode_method"] == "llm"
    assert llm[0]["decoded_kb_version"] == meta["kb_version"]
    # both rejects got fresh, self-contained retry prompts
    assert sorted(p.name for p in (out / "retry").iterdir()) == ["001.txt", "002.txt"]
    assert "REJECTED" in (out / "retry" / "001.txt").read_text(encoding="utf-8")
    assert "verbatim" in (out / "retry" / "002.txt").read_text(encoding="utf-8")
    # combined = deterministic rows + accepted llm rows
    assert [r["raw_label"] for r in read_jsonl(combined)] == [LABEL_DET, LABEL_OK]
