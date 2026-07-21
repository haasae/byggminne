"""Data-profiling layer, step 2: test decode guesses against series statistics.

Implements CLAUDE.md section 4 (name = hypothesis, data = test) for the checks
that per-label statistics can answer. Joins decoder outputs to stats by verbatim
raw_label and runs deterministic checks; conflicts become the human-review
queue. Decoder outputs are never mutated -- an augmented COPY gets data_checks.

Phase 1 checks (temp_correlation stays null until weather data lands in Phase 2):
- binary-expected   guessed status / BI / BO / BV  -> at most 2 distinct values
- av-trap           guessed analog but exactly 2 distinct values observed
- range             temperatur / co2 / AO-command within physically plausible bounds
- dead-point        a constant series can confirm nothing -> human look
- energy-monotonic  guessed cumulative energy -> non-decreasing values
- file-kind         BACnet family implied by 'AV/BV punkter' file vs object_type

    python -m src.profile.cross_check --stats runs/profile/tasen/stats.jsonl \
        --outputs runs/<id>/outputs.jsonl --out-dir runs/<id>
"""
import argparse
from pathlib import Path

from src.common.io_utils import configure_stdout_utf8, read_jsonl, write_jsonl
from src.score.normalize import normalize_text
from src.validate.schema_validator import build_validator, validate_instance

PASS = "PASS"
CONFLICT = "CONFLICT"
INCONCLUSIVE = "INCONCLUSIVE"
NOT_APPLICABLE = "N/A"

_ANALOG_TYPES = {"AV", "AI", "AO"}
_BINARY_TYPES = {"BV", "BI", "BO"}

# Physically plausible bounds per guessed measurement_type.
_RANGES = {
    "temperatur": (-40.0, 130.0),   # degrees C, generous HVAC envelope
    "co2": (0.0, 10000.0),          # ppm
}


def _fmt_range(st):
    if st["n_num"] == 0:
        return "no numeric values"
    return f"observed [{st['min']:g}, {st['max']:g}], mean {st['mean']:.4g}, n={st['n_num']}"


def check_binary_expected(decoded, st):
    """status / BI / BO / BV guesses predict at most 2 distinct values."""
    binary_guess = (
        decoded.get("object_type") in _BINARY_TYPES
        or decoded.get("measurement_type") == "status"
    )
    if not binary_guess:
        return NOT_APPLICABLE, None
    if st["n_num"] == 0:
        return INCONCLUSIVE, "no numeric values to test"
    if st["distinct_capped"]:
        return CONFLICT, f"guessed binary but > {32} distinct values observed"
    if st["distinct_count"] <= 2:
        values = st.get("values")
        shown = f" (values {values})" if values else ""
        return PASS, f"{st['distinct_count']} distinct value(s){shown}"
    return CONFLICT, (f"guessed binary but {st['distinct_count']} distinct values"
                      f" (values {st.get('values')})")


def check_av_trap(decoded, st):
    """An analog guess with exactly 2 observed values = the AV-as-binary trap.

    Exception: a SETPOINT holding 2 values is normal scheduling behavior
    (day/night switching, e.g. a pressure setpoint of 50/120 Pa), not a
    mislabeled binary -- same doctrine as the dead-point constant exception.
    """
    analog_guess = (
        decoded.get("object_type") in _ANALOG_TYPES
        or decoded.get("measurement_type") in ("temperatur", "co2", "trykk")
    )
    if not analog_guess:
        return NOT_APPLICABLE, None
    if decoded.get("measurement_type") == "status":
        # The decode already treats this analog-typed object as semantically
        # binary (a recognized AV-as-binary point) -- 2 values CONFIRM it.
        if st["n_num"] and st["distinct_count"] is not None and st["distinct_count"] <= 2:
            return PASS, (f"known AV-as-binary point: {st['distinct_count']} distinct"
                          f" value(s) {st.get('values')} consistent with status semantics")
        return NOT_APPLICABLE, None
    if st["n_num"] == 0:
        return INCONCLUSIVE, "no numeric values to test"
    if st["distinct_count"] == 2:
        function = normalize_text(decoded.get("function")) or ""
        if any(w in function for w in ("settpunkt", "setpoint", "borverdi", "grenseverdi")):
            return PASS, (f"setpoint switching between 2 values {st.get('values')}"
                          " -- normal day/night scheduling, not the AV trap")
        return CONFLICT, (f"guessed analog but only 2 distinct values"
                          f" {st.get('values')} -- semantically binary (AV trap)")
    return PASS, "value diversity consistent with an analog point"


def check_range(decoded, st):
    """Observed values must sit in the plausible envelope of the guessed quantity."""
    mtype = decoded.get("measurement_type")
    is_ao_command = decoded.get("object_type") == "AO" and mtype == "kommando"
    if mtype not in _RANGES and mtype != "trykk" and not is_ao_command:
        return NOT_APPLICABLE, None
    if st["n_num"] == 0:
        return INCONCLUSIVE, "no numeric values to test"
    if mtype == "trykk":
        # Unit unknown (Pa/kPa/bar): no hard bounds; surface the evidence.
        return INCONCLUSIVE, f"trykk unit unknown; {_fmt_range(st)}"
    lo, hi = (0.0, 100.0) if is_ao_command else _RANGES[mtype]
    what = "AO command (assumed %)" if is_ao_command else mtype
    if st["min"] >= lo and st["max"] <= hi:
        return PASS, f"{what} within [{lo:g}, {hi:g}]; {_fmt_range(st)}"
    return CONFLICT, f"{what} outside [{lo:g}, {hi:g}]; {_fmt_range(st)}"


def check_dead_point(decoded, st):
    """A constant series usually confirms nothing about the name-based guess.

    Exceptions where constant IS the expected behavior:
    - a setpoint that was never adjusted (settpunkt/setpoint/borverdi);
    - an alarm that never fired (constant 0).
    A constantly-ACTIVE alarm or any other constant point stays INCONCLUSIVE.
    """
    if st["n_num"] == 0:
        return INCONCLUSIVE, "no numeric values at all"
    if st["distinct_count"] == 1:
        function = normalize_text(decoded.get("function")) or ""
        value = st["values"][0] if st.get("values") else None
        if any(word in function for word in ("settpunkt", "setpoint", "borverdi")):
            return PASS, (f"constant value {value:g} -- consistent with a setpoint"
                          " that was never adjusted")
        if "alarm" in function and value == 0.0:
            return PASS, "constant 0 -- alarm never fired (normal)"
        return INCONCLUSIVE, (f"constant value {st.get('values')} over"
                              f" [{st['first_ts']} .. {st['last_ts']}] -- dead or"
                              " never-active point; cannot confirm the decode")
    return PASS, ("value changes over time"
                  + (f" ({st['distinct_count']} distinct)" if st["distinct_count"] is not None
                     else " (> cap distinct)"))


def check_energy_monotonic(decoded, st):
    """A cumulative energy meter must be (near-)monotonically increasing."""
    if decoded.get("measurement_type") != "energi":
        return NOT_APPLICABLE, None
    mono = st["monotonic_nondecreasing"]
    if mono is None:
        return INCONCLUSIVE, "not enough values to assess monotonicity"
    if mono:
        return PASS, "series is monotonically non-decreasing"
    return CONFLICT, (f"guessed cumulative energy but value decreases"
                      f" {st['n_decreases']} time(s)")


def check_file_kind(decoded, st):
    """The 'AV/BV punkter' source file family should agree with object_type."""
    obj = decoded.get("object_type")
    kinds = set(st.get("file_kinds") or ())
    if obj is None or not kinds:
        return NOT_APPLICABLE, None
    if kinds == {"AV"} and obj in _BINARY_TYPES:
        return CONFLICT, f"decoded {obj} but label only appears in an 'AV punkter' file"
    if kinds == {"BV"} and obj in _ANALOG_TYPES:
        return CONFLICT, f"decoded {obj} but label only appears in a 'BV punkter' file"
    if len(kinds) > 1:
        return INCONCLUSIVE, f"label appears in mixed file kinds {sorted(kinds)}"
    if obj in _ANALOG_TYPES | _BINARY_TYPES:
        return PASS, f"object_type {obj} consistent with '{next(iter(kinds))} punkter' file"
    return NOT_APPLICABLE, None  # MV/MI/MO have no AV/BV file family


CHECKS = (
    ("binary-expected", check_binary_expected),
    ("av-trap", check_av_trap),
    ("range", check_range),
    ("dead-point", check_dead_point),
    ("energy-monotonic", check_energy_monotonic),
    ("file-kind", check_file_kind),
)


def run_checks(decoded, st):
    """All checks for one (decoded, stats) pair -> list of result dicts."""
    results = []
    for name, fn in CHECKS:
        verdict, evidence = fn(decoded, st)
        if verdict == NOT_APPLICABLE:
            continue
        results.append({"name": name, "verdict": verdict, "evidence": evidence})
    return results


def build_data_checks(st, results):
    """The schema's data_checks object for one label."""
    return {
        "distinct_values": st["distinct_count"],
        "monotonic": st["monotonic_nondecreasing"],
        "temp_correlation": None,  # Phase 2 (needs outdoor temperature)
        "conflict": any(r["verdict"] == CONFLICT for r in results),
    }


def cross_check(outputs, stats_rows):
    """Join outputs to stats and run all checks.

    Returns (checked, missing_stats) where checked is a list of
    {raw_label, checks, data_checks, stats} and missing_stats lists output
    labels with no stats row.
    """
    by_label = {row["raw_label"]: row for row in stats_rows}
    checked, missing = [], []
    for decoded in outputs:
        label = decoded.get("raw_label")
        st = by_label.get(label)
        if st is None:
            missing.append(label)
            continue
        results = run_checks(decoded, st)
        checked.append({
            "raw_label": label,
            "checks": results,
            "data_checks": build_data_checks(st, results),
            "stats": st,
        })
    return checked, missing


def _short(label, max_len=55):
    return label if len(label) <= max_len else "…" + label[-(max_len - 1):]


def render_markdown(checked, missing, n_outputs, n_stats):
    verdict_counts = {PASS: 0, CONFLICT: 0, INCONCLUSIVE: 0}
    for row in checked:
        for r in row["checks"]:
            verdict_counts[r["verdict"]] += 1
    n_conflict_labels = sum(1 for row in checked if row["data_checks"]["conflict"])

    L = ["# Data cross-check report (Phase 1: per-label statistics)", ""]
    L.append("Name = hypothesis, data = test (CLAUDE.md section 4). A CONFLICT means "
             "the measurement data contradicts the name-based decode -- review it; "
             "an INCONCLUSIVE point could not be confirmed either way.")
    L.append("")
    L.append("## At a glance")
    L.append("")
    L.append(f"- Decoded labels checked: **{len(checked)}** of {n_outputs} outputs "
             f"(stats available for {n_stats} labels)")
    L.append(f"- Checks run: {sum(verdict_counts.values())} -> "
             f"**{verdict_counts[PASS]} PASS**, **{verdict_counts[CONFLICT]} CONFLICT**, "
             f"{verdict_counts[INCONCLUSIVE]} INCONCLUSIVE")
    L.append(f"- Labels with at least one conflict: **{n_conflict_labels}**")
    if missing:
        L.append(f"- Output labels with NO stats (not in the profiled data): {len(missing)}")
    L.append("")

    L.append("## Verdict overview")
    L.append("")
    L.append("| # | label (tail) | checks | conflict? |")
    L.append("|---|---|---|---|")
    for i, row in enumerate(checked):
        cell = " ".join(f"{r['name']}:{r['verdict']}" for r in row["checks"]) or "-"
        flag = "**YES**" if row["data_checks"]["conflict"] else "no"
        L.append(f"| {i} | `{_short(row['raw_label'])}` | {cell} | {flag} |")
    L.append("")

    queue = [row for row in checked
             if row["data_checks"]["conflict"]
             or any(r["verdict"] == INCONCLUSIVE for r in row["checks"])]
    L.append("## Human-review queue (conflicts + inconclusive)")
    L.append("")
    if not queue:
        L.append("_Empty -- every applicable check passed._")
    for row in queue:
        L.append(f"### `{row['raw_label']}`")
        for r in row["checks"]:
            if r["verdict"] in (CONFLICT, INCONCLUSIVE):
                L.append(f"- **{r['name']}: {r['verdict']}** -- {r['evidence']}")
        L.append("")

    L.append("## Per-label details")
    L.append("")
    for i, row in enumerate(checked):
        st = row["stats"]
        L.append(f"### {i}. `{row['raw_label']}`")
        L.append("")
        L.append(f"- data: n={st['n_num']} ({st['n_bad_values']} bad), "
                 f"range [{st['min']:g}, {st['max']:g}]"
                 if st["n_num"] else "- data: no numeric values")
        if st["n_num"]:
            distinct = (st["distinct_count"] if st["distinct_count"] is not None
                        else f"> {32} (capped)")
            L.append(f"- distinct values: {distinct}"
                     + (f" = {st['values']}" if st.get("values") else ""))
            L.append(f"- span: {st['first_ts']} .. {st['last_ts']}; "
                     f"files: {', '.join(st['files'])}")
        for r in row["checks"]:
            L.append(f"- **{r['name']}: {r['verdict']}** -- {r['evidence']}")
        L.append("")
    if missing:
        L.append("## Output labels without stats")
        L.append("")
        for label in missing:
            L.append(f"- `{label}`")
        L.append("")
    return "\n".join(L)


def main() -> int:
    configure_stdout_utf8()
    ap = argparse.ArgumentParser(
        description="Cross-check decoded outputs against per-label series statistics."
    )
    ap.add_argument("--stats", required=True, help="stats.jsonl from series_stats")
    ap.add_argument("--outputs", required=True, help="decoder outputs.jsonl")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--schema", help="schema path (defaults to schema/decoded_label.schema.json)")
    args = ap.parse_args()

    outputs = read_jsonl(args.outputs)
    stats_rows = read_jsonl(args.stats)
    checked, missing = cross_check(outputs, stats_rows)

    out_dir = Path(args.out_dir)

    # data_checks.jsonl: the check evidence, one row per checked label.
    write_jsonl(out_dir / "data_checks.jsonl", [
        {"raw_label": row["raw_label"], "checks": row["checks"],
         "data_checks": row["data_checks"]}
        for row in checked
    ])

    # outputs_checked.jsonl: augmented COPY of the outputs with data_checks
    # filled in; the original outputs.jsonl is never touched.
    by_label = {row["raw_label"]: row for row in checked}
    validator = build_validator(args.schema)
    augmented, n_invalid = [], 0
    for decoded in outputs:
        copy = dict(decoded)
        row = by_label.get(copy.get("raw_label"))
        if row is not None and not copy.get("schema_invalid"):
            copy["data_checks"] = row["data_checks"]
        augmented.append(copy)
        if validate_instance(copy, validator):
            n_invalid += 1
    write_jsonl(out_dir / "outputs_checked.jsonl", augmented)

    report = render_markdown(checked, missing, len(outputs), len(stats_rows))
    (out_dir / "cross_check.md").write_text(report, encoding="utf-8")

    n_conflicts = sum(1 for row in checked if row["data_checks"]["conflict"])
    print(f"checked {len(checked)}/{len(outputs)} labels "
          f"({n_conflicts} with conflicts, {len(missing)} without stats, "
          f"{n_invalid} augmented rows schema-invalid) -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
