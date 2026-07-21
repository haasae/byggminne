"""Graph-readiness gaps of a decoded row -- the shared vocabulary between the
enrichment selector (src/decode/enrichment.py) and the graph-readiness report
(src/brick/readiness_report.py).

A "gap" is a reason a decoded label is not yet useful to the Brick knowledge
graph. The selector uses a subset of gaps to pick LLM-enrichment candidates;
the report shows all of them.
"""

GAP_PRIMARY_SYSTEM = "primary_system"      # no NS 3451 system -> no system node
GAP_POINT_SEMANTICS = "point_semantics"    # neither measurement_type nor function
GAP_BUILDING = "building"                  # no building -> point floats at site level
GAP_LOW_CONFIDENCE = "low_confidence"      # at/below the deterministic floor

# Confidence at (or below) this value marks the decode as minimum-viable only:
# it cleared deterministic_batch.MIN_CONFIDENCE but carries no corroborating
# evidence beyond a single rule hit.
LOW_CONFIDENCE_BAR = 0.4


def readiness_gaps(row):
    """The row's graph-readiness gaps, as a tuple of GAP_* constants."""
    gaps = []
    if row.get("primary_system") is None:
        gaps.append(GAP_PRIMARY_SYSTEM)
    if row.get("measurement_type") is None and row.get("function") is None:
        gaps.append(GAP_POINT_SEMANTICS)
    if not (row.get("location") or {}).get("building"):
        gaps.append(GAP_BUILDING)
    if (row.get("confidence") or 0) <= LOW_CONFIDENCE_BAR:
        gaps.append(GAP_LOW_CONFIDENCE)
    return tuple(gaps)
