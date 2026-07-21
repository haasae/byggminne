"""Data-profiling layer, Phase 3: relationships between decoded points.

Two halves, same doctrine as the rest of src/profile (name = hypothesis,
data = test):

1. **Infer** which decoded labels belong together, from structural tokens in
   the raw label (vendor-specific heuristics, tested):
   - same_system      -- shared system token, e.g. `320001` / `320001_bygg5`
   - same_controller  -- shared `<controlnumber>-OU<nnn>` segment
   - same_equipment   -- shared equipment token, e.g. `Spillvannspumpe_P2`,
                         `IK001_TEST`
   This fills the schema's `relationships` array on an augmented COPY of the
   outputs (`outputs_linked.jsonl`); the decoder's outputs stay untouched.

2. **Verify** the system-level story against the measurement data:
   - directional: an analog, non-setpoint member of a heating system (32xx)
     should correlate NEGATIVELY with the outdoor reference; a cooling system
     (37xx) member POSITIVELY (CLAUDE.md section 4).
   - tur/retur: when a group contains supply (R_4xx) and return (R_5xx)
     temperature roles, supply should read above return most of the time.
   - co-behavior: pairwise Pearson within a group -- reported as SUPPORTED /
     NO_SIGNAL evidence, never CONFLICT (uncorrelated members do not falsify
     shared membership).

    python -m src.profile.relationship_check "data/raw/tasen/*.csv" \
        --outputs runs/<id>/outputs.jsonl --stats runs/profile/tasen/stats.jsonl \
        --outdoor-ref "OU001/FCB.Local Application.-RT401." --out-dir runs/<id>
"""
import argparse
import itertools
from pathlib import Path

from src.common.io_utils import configure_stdout_utf8, read_jsonl, write_jsonl
from src.common.label_tokens import group_keys, point_role
from src.profile.seasonal_check import load_series, pearson, resolve_reference
from src.profile.series_stats import _resolve
from src.score.normalize import normalize_text
from src.validate.schema_validator import build_validator, validate_instance

PASS = "PASS"
CONFLICT = "CONFLICT"
SUPPORTED = "SUPPORTED"
NO_SIGNAL = "NO_SIGNAL"
SKIPPED = "SKIPPED"

# Verdict thresholds (tunable; documented in the report).
DIRECTIONAL_R = 0.2       # |r| a heating/cooling member must show vs outdoor
CO_BEHAVIOR_R = 0.3       # |r| for two group members to count as co-behaving
TUR_RETUR_PASS = 0.9      # fraction of samples with tur > retur for a PASS
TUR_RETUR_FAIL = 0.5      # below this the ordering is contradicted

# Structural grouping helpers (group_keys, point_role) live in
# src/common/label_tokens.py, shared with the decode rules engine.

def build_groups(outputs):
    """{(kind, key): [raw_label, ...]} for all decoded outputs."""
    groups = {}
    for row in outputs:
        label = row.get("raw_label")
        for kind, key in group_keys(label):
            groups.setdefault((kind, key), []).append(label)
    # Only groups with 2+ members define relationships.
    return {gk: labels for gk, labels in groups.items() if len(labels) >= 2}


def build_relationships(groups):
    """{raw_label: [{type, target_raw_label}, ...]} (deduplicated)."""
    rel = {}
    seen = set()
    for (kind, _key), labels in sorted(groups.items()):
        for a, b in itertools.permutations(labels, 2):
            if (a, b, kind) in seen:
                continue
            seen.add((a, b, kind))
            rel.setdefault(a, []).append({"type": kind, "target_raw_label": b})
    return rel


# --- data verification --------------------------------------------------------

def _is_constant(stats_row):
    return stats_row is not None and stats_row.get("distinct_count") == 1


def _is_binaryish(stats_row):
    return stats_row is not None and stats_row.get("is_binary")


def _is_setpoint(decoded):
    function = normalize_text(decoded.get("function")) or ""
    return any(w in function for w in ("settpunkt", "setpoint", "borverdi"))


def directional_check(decoded, stats_row, series, outdoor):
    """Heating members anti-correlate with outdoor; cooling members correlate."""
    code = (decoded.get("primary_system") or {}).get("code") or ""
    if code.startswith("32"):
        expect, expect_txt = -1, "negative (heating)"
    elif code.startswith("37"):
        expect, expect_txt = +1, "positive (cooling)"
    else:
        return None
    if _is_setpoint(decoded):
        return {"verdict": SKIPPED, "evidence": "setpoint: regulation target, not load-driven"}
    if _is_constant(stats_row):
        return {"verdict": SKIPPED, "evidence": "constant series"}
    if _is_binaryish(stats_row):
        return {"verdict": SKIPPED, "evidence": "binary series: correlation not meaningful here"}
    r, n = pearson(series, outdoor)
    if r is None:
        return {"verdict": SKIPPED, "evidence": f"correlation undefined (n={n})"}
    if decoded.get("measurement_type") == "kommando":
        # Actuator commands are sign-ambiguous by installation (direct vs
        # reverse acting: a mixing valve may open MORE in warm weather to cool
        # the supply), so the load-direction rule cannot judge them.
        return {"verdict": SKIPPED,
                "evidence": f"command output: sign is actuator-direction-specific"
                            f" (r={r:+.3f} vs outdoor, n={n}, recorded as evidence only)"}
    evidence = f"r={r:+.3f} vs outdoor (n={n}), expected {expect_txt}, threshold {DIRECTIONAL_R}"
    if expect * r >= DIRECTIONAL_R:
        return {"verdict": PASS, "evidence": evidence}
    if expect * r <= -DIRECTIONAL_R:
        return {"verdict": CONFLICT, "evidence": evidence}
    return {"verdict": NO_SIGNAL, "evidence": evidence}


def tur_retur_check(label_a, series_a, label_b, series_b):
    """Supply (x4xx) should read above return (x5xx) most of the time."""
    common = series_a.keys() & series_b.keys()
    n = len(common)
    if n < 2:
        return {"verdict": SKIPPED, "evidence": f"only {n} aligned samples"}
    above = sum(1 for ts in common if series_a[ts] > series_b[ts])
    frac = above / n
    evidence = f"tur > retur in {100 * frac:.1f}% of {n} aligned samples"
    if frac >= TUR_RETUR_PASS:
        return {"verdict": PASS, "evidence": evidence}
    if frac < TUR_RETUR_FAIL:
        return {"verdict": CONFLICT, "evidence": evidence}
    return {"verdict": NO_SIGNAL, "evidence": evidence}


def co_behavior_check(series_a, series_b):
    """Pairwise Pearson as SUPPORTED/NO_SIGNAL evidence -- never a CONFLICT."""
    r, n = pearson(series_a, series_b)
    if r is None:
        return {"verdict": SKIPPED, "evidence": f"correlation undefined (n={n})"}
    evidence = f"r={r:+.3f} (n={n}), threshold {CO_BEHAVIOR_R}"
    return {"verdict": SUPPORTED if abs(r) >= CO_BEHAVIOR_R else NO_SIGNAL,
            "evidence": evidence}


def verify_groups(groups, outputs_by_label, stats_by_label, series, outdoor_label):
    """Run all data checks; return a list of finding dicts."""
    findings = []
    outdoor = series.get(outdoor_label, {})

    # Directional member checks (per decoded label, once).
    for row in outputs_by_label.values():
        label = row["raw_label"]
        if label == outdoor_label:
            continue
        result = directional_check(row, stats_by_label.get(label),
                                   series.get(label, {}), outdoor)
        if result:
            findings.append({"check": "system-vs-outdoor", "labels": [label],
                             "group": (row.get("primary_system") or {}).get("code"),
                             **result})

    for (kind, key), labels in sorted(groups.items()):
        # tur/retur ordering for same-letter temperature-ish pairs.
        by_role = {}
        for label in labels:
            letters, side = point_role(label)
            if letters and side in ("4", "5"):
                by_role.setdefault(letters, {}).setdefault(side, []).append(label)
        for letters, sides in by_role.items():
            for a in sides.get("4", []):
                for b in sides.get("5", []):
                    result = tur_retur_check(a, series.get(a, {}), b, series.get(b, {}))
                    findings.append({"check": f"tur-retur ({letters})",
                                     "labels": [a, b], "group": f"{kind}:{key}", **result})

        # Pairwise co-behavior (skip constants; they carry no signal).
        for a, b in itertools.combinations(sorted(labels), 2):
            if _is_constant(stats_by_label.get(a)) or _is_constant(stats_by_label.get(b)):
                findings.append({"check": "co-behavior", "labels": [a, b],
                                 "group": f"{kind}:{key}", "verdict": SKIPPED,
                                 "evidence": "constant member"})
                continue
            result = co_behavior_check(series.get(a, {}), series.get(b, {}))
            findings.append({"check": "co-behavior", "labels": [a, b],
                             "group": f"{kind}:{key}", **result})
    return findings


# --- report -------------------------------------------------------------------

def _short(label, max_len=48):
    return label if len(label) <= max_len else "…" + label[-(max_len - 1):]


def render_markdown(groups, relationships, findings, outdoor_label):
    counts = {}
    for f in findings:
        counts[f["verdict"]] = counts.get(f["verdict"], 0) + 1

    L = ["# Relationship check report (Phase 3)", ""]
    L.append(f"Outdoor reference: `{outdoor_label}`")
    L.append("")
    L.append("## At a glance")
    L.append("")
    L.append(f"- Groups inferred: **{len(groups)}** -> "
             f"{sum(len(v) for v in relationships.values())} directed relationships")
    summary = ", ".join(f"**{n} {v}**" for v, n in sorted(counts.items()))
    L.append(f"- Data findings: {summary if counts else 'none'}")
    L.append("")

    L.append("## Inferred groups")
    L.append("")
    for (kind, key), labels in sorted(groups.items()):
        L.append(f"- `{key}` ({kind}, {len(labels)} members)")
        for label in labels:
            L.append(f"  - `{_short(label, 70)}`")
    L.append("")

    L.append("## Data findings")
    L.append("")
    L.append("| check | group | labels | verdict | evidence |")
    L.append("|---|---|---|---|---|")
    for f in findings:
        labels = " / ".join(f"`{_short(l)}`" for l in f["labels"])
        verdict = f"**{f['verdict']}**" if f["verdict"] in (PASS, CONFLICT) else f["verdict"]
        L.append(f"| {f['check']} | {f.get('group') or '-'} | {labels} | {verdict} | {f['evidence']} |")
    L.append("")

    conflicts = [f for f in findings if f["verdict"] == CONFLICT]
    L.append("## Human-review queue (conflicts)")
    L.append("")
    if not conflicts:
        L.append("_No relationship-level conflicts._")
    for f in conflicts:
        L.append(f"- **{f['check']}** on {', '.join(f['labels'])}: {f['evidence']}")
    L.append("")
    return "\n".join(L)


def main() -> int:
    configure_stdout_utf8()
    ap = argparse.ArgumentParser(
        description="Infer and data-verify relationships between decoded labels."
    )
    ap.add_argument("inputs", nargs="+", help="raw CSV files or glob patterns")
    ap.add_argument("--outputs", required=True, help="decoder outputs.jsonl")
    ap.add_argument("--stats", required=True, help="stats.jsonl from series_stats")
    ap.add_argument("--outdoor-ref", required=True,
                    help="substring uniquely identifying the outdoor-temperature label")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--schema", help="schema path (defaults to schema/decoded_label.schema.json)")
    args = ap.parse_args()

    outputs = read_jsonl(args.outputs)
    outputs_by_label = {row["raw_label"]: row for row in outputs}
    stats_by_label = {row["raw_label"]: row for row in read_jsonl(args.stats)}

    groups = build_groups(outputs)
    relationships = build_relationships(groups)

    # Load only the series we need: group members with data checks + all decoded
    # labels (for the directional check) + the outdoor reference.
    outdoor_label = resolve_reference(list(stats_by_label), args.outdoor_ref)
    needed = {label for labels in groups.values() for label in labels}
    needed.update(outputs_by_label)
    needed.add(outdoor_label)
    series = load_series(_resolve(args.inputs), needed)

    findings = verify_groups(groups, outputs_by_label, stats_by_label, series, outdoor_label)

    out_dir = Path(args.out_dir)
    write_jsonl(out_dir / "relationships.jsonl", findings)

    # Augmented copy with the relationships array filled (schema-valid).
    validator = build_validator(args.schema)
    augmented, n_invalid = [], 0
    for row in outputs:
        copy = dict(row)
        rels = relationships.get(copy.get("raw_label"))
        if rels and not copy.get("schema_invalid"):
            copy["relationships"] = rels
        augmented.append(copy)
        if validate_instance(copy, validator):
            n_invalid += 1
    write_jsonl(out_dir / "outputs_linked.jsonl", augmented)

    report = render_markdown(groups, relationships, findings, outdoor_label)
    (out_dir / "relationships.md").write_text(report, encoding="utf-8")

    n_conflicts = sum(1 for f in findings if f["verdict"] == CONFLICT)
    print(f"{len(groups)} groups, {len(findings)} findings "
          f"({n_conflicts} conflicts, {n_invalid} augmented rows schema-invalid) -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
