"""Join decoder outputs to gold by the verbatim raw_label key.

Integrity problems (a dropped label, an extra output, a duplicate key, or a
decoder that silently altered raw_label) are reported separately from field
errors so they cannot masquerade as accuracy.
"""
from dataclasses import dataclass, field
from typing import List, Tuple

from src.score.normalize import normalize_text


@dataclass
class Alignment:
    matched: List[Tuple[str, dict, dict]] = field(default_factory=list)   # (raw_label, pred, gold)
    missing_in_outputs: List[str] = field(default_factory=list)           # gold key absent from outputs
    extra_in_outputs: List[str] = field(default_factory=list)             # output key absent from gold
    duplicate_output_keys: List[str] = field(default_factory=list)
    duplicate_gold_keys: List[str] = field(default_factory=list)
    near_miss_keys: List[Tuple[str, str]] = field(default_factory=list)   # (output_key, normalized-equal gold_key)


def _index(rows):
    index, dups = {}, []
    for row in rows:
        key = row.get("raw_label")
        if key in index:
            dups.append(key)
        index[key] = row
    return index, dups


def align(outputs, gold) -> Alignment:
    out_index, out_dups = _index(outputs)
    gold_index, gold_dups = _index(gold)

    result = Alignment(duplicate_output_keys=out_dups, duplicate_gold_keys=gold_dups)

    for key, gold_row in gold_index.items():
        if key in out_index:
            result.matched.append((key, out_index[key], gold_row))
        else:
            result.missing_in_outputs.append(key)

    norm_gold = {normalize_text(k): k for k in gold_index}
    for key in out_index:
        if key in gold_index:
            continue
        result.extra_in_outputs.append(key)
        near = norm_gold.get(normalize_text(key))
        if near is not None:
            result.near_miss_keys.append((key, near))

    return result
