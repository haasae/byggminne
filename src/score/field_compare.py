"""Per-field comparison -> a verdict, driven entirely by the field registry.

Verdicts separate the two ways a decode can be "incomplete vs wrong":
- UNDER_FILL: gold has a value, the model left it null (a knowledge-base gap).
- OVER_FILL:  the model invented a value where gold is null -- the dangerous
              class CLAUDE.md warns about ("never invent a meaning").
"""
from dataclasses import dataclass
from typing import Any, List, Optional

from src.common.fields import BOOL, CODE, FREE_TEXT, get_value
from src.score.normalize import code_prefix, normalize_text

CORRECT = "CORRECT"
UNDER_FILL = "UNDER_FILL"
OVER_FILL = "OVER_FILL"
WRONG_VALUE = "WRONG_VALUE"


@dataclass
class FieldResult:
    path: str
    tier: str
    kind: str
    verdict: str
    predicted: Any
    gold: Any
    gold_nonnull: bool
    exact: Optional[bool] = None   # CODE only: full-code exact match (secondary metric)

    @property
    def correct(self) -> bool:
        return self.verdict == CORRECT


def _values_equal(kind, pv, gv) -> bool:
    if kind == FREE_TEXT:
        return normalize_text(pv) == normalize_text(gv)
    if kind == BOOL:
        return bool(pv) == bool(gv)
    # ENUM: schema enums are ASCII; compare verbatim apart from surrounding space.
    return str(pv).strip() == str(gv).strip()


def compare_field(spec, pred_instance, gold_instance) -> FieldResult:
    pv = get_value(pred_instance, spec.path)
    gv = get_value(gold_instance, spec.path)
    gold_nonnull = gv is not None

    if pv is None and gv is None:
        return FieldResult(spec.path, spec.tier, spec.kind, CORRECT, pv, gv, gold_nonnull)
    if pv is None:
        return FieldResult(spec.path, spec.tier, spec.kind, UNDER_FILL, pv, gv, gold_nonnull)
    if gv is None:
        return FieldResult(spec.path, spec.tier, spec.kind, OVER_FILL, pv, gv, gold_nonnull)

    # Both present.
    if spec.kind == CODE:
        pp, gp = code_prefix(pv), code_prefix(gv)
        if pp is None and gp is None:
            correct = str(pv).strip() == str(gv).strip()
        else:
            correct = pp == gp
        exact = str(pv).strip() == str(gv).strip()
        verdict = CORRECT if correct else WRONG_VALUE
        return FieldResult(spec.path, spec.tier, spec.kind, verdict, pv, gv, gold_nonnull, exact=exact)

    verdict = CORRECT if _values_equal(spec.kind, pv, gv) else WRONG_VALUE
    return FieldResult(spec.path, spec.tier, spec.kind, verdict, pv, gv, gold_nonnull)


def compare_row(pred_instance, gold_instance, specs) -> List[FieldResult]:
    return [compare_field(spec, pred_instance, gold_instance) for spec in specs]
