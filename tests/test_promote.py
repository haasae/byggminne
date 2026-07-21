from src.common.io_utils import read_jsonl, write_jsonl
from src.profile.promote import approve, find_candidates

CLEAN = "SITE:111-OU001/-XQ401.#1"
CONFLICTED = "SITE:111-OU001/-XQ402.#1"
DETERMINISTIC = "SITE:111-OU001/-RT401.#1"


def _row(raw_label, method="rules+llm", **over):
    row = {
        "raw_label": raw_label, "source_type": "bacnet",
        "measurement_type": "temperatur", "function": "temperatur",
        "primary_system": {"code": "3200", "description": "Varme"},
        "confidence": 0.6, "reasoning": "det + llm", "validated": False,
        "decode_method": method,
    }
    row.update(over)
    return row


def _checks(raw_label, verdicts):
    return {"raw_label": raw_label,
            "checks": [{"name": n, "verdict": v, "evidence": f"{n} evidence"}
                       for n, v in verdicts]}


OUTPUTS = [
    _row(CLEAN),
    _row(CONFLICTED),
    _row(DETERMINISTIC, method="rules"),     # not LLM-touched -> never nominated
]
CHECKS = [
    _checks(CLEAN, [("range", "PASS"), ("dead-point", "PASS")]),
    _checks(CONFLICTED, [("range", "PASS"), ("av-trap", "CONFLICT")]),
    _checks(DETERMINISTIC, [("range", "PASS")]),
]


def test_candidate_bar():
    candidates, evidence = find_candidates(OUTPUTS, CHECKS)
    assert [c["raw_label"] for c in candidates] == [CLEAN]
    assert [c["name"] for c in evidence[CLEAN]] == ["range", "dead-point"]


def test_no_data_evidence_means_not_promotable():
    candidates, _ = find_candidates([_row(CLEAN)], [])
    assert candidates == []


def test_approve_appends_with_human_flag_and_proof(tmp_path):
    store = tmp_path / "store.jsonl"
    write_jsonl(store, [_row("already there", validated=True)])
    candidates, evidence = find_candidates(OUTPUTS, CHECKS)

    appended, skipped = approve(candidates, evidence,
                                [CLEAN, CONFLICTED, "already there"],
                                store_path=str(store))
    assert [r["raw_label"] for r in appended] == [CLEAN]
    assert skipped == [CONFLICTED, "already there"]   # not candidate / duplicate

    rows = read_jsonl(store)
    assert len(rows) == 2
    promoted = rows[1]
    assert promoted["validated"] is True
    assert "human-approved after data cross-check" in promoted["reasoning"]
    assert "range PASS" in promoted["reasoning"]
    # the candidate file row itself must stay unvalidated
    assert candidates[0]["validated"] is False
