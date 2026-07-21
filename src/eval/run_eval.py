"""One-command manual test of the decode pipeline: decode -> score -> showcase.

No decode or scoring logic lives here; this driver chains the existing layers
and condenses their outputs into a single summary.md:

1. src.decode.deterministic_batch -- rules + retrieval, zero LLM tokens
2. src.score.run_score            -- accuracy vs gold, when a gold file exists
3. src.score.showcase             -- human-readable rendering, no gold needed

It also reports the validated-store overlap for the batch: an exact store hit
replays a stored decode, so accuracy on those labels measures KB recall, not
generalization. To measure generalization, score a batch of unseen labels.

    # decode + score + showcase with the conventional paths
    python -m src.eval.run_eval --batch b001

    # after the /decode skill appended LLM rows: score that outputs file instead
    python -m src.eval.run_eval --batch b001 --outputs runs/<id>/outputs.jsonl

Conventions (each overridable): input `data/eval/batches/<batch>/input.jsonl`,
gold `tests/gold/<batch>/gold.jsonl`, out-dir `runs/<batch>_eval_<kb_version>`.
"""
import argparse
from collections import Counter
from pathlib import Path

from src.common.io_utils import configure_stdout_utf8, read_jsonl, repo_root
from src.decode import deterministic_batch
from src.decode.context_pack import build_context_pack
from src.decode.retrieval import STORE_FILE, signature
from src.score.run_score import score, write_score_reports
from src.score.showcase import render_showcase


def _pct(x):
    return "n/a" if x is None else f"{100 * x:.1f}%"


def store_overlap(rows, store_path=None):
    """Exact / sibling / unseen label counts for a batch vs the validated store."""
    path = repo_root() / (store_path or STORE_FILE)
    store_rows = read_jsonl(path) if path.exists() else []
    labels = {r["raw_label"] for r in store_rows}
    sigs = {signature(r["raw_label"]) for r in store_rows}
    counts = {"exact": 0, "sibling": 0, "unseen": 0, "store_rows": len(store_rows)}
    for row in rows:
        label = row["raw_label"]
        if label in labels:
            counts["exact"] += 1
        elif signature(label) in sigs:
            counts["sibling"] += 1
        else:
            counts["unseen"] += 1
    return counts


def _weakest_fields(metrics, limit=3):
    """Fields with gold-non-null misses, worst first."""
    stats = [
        st for st in metrics["field_stats"].values()
        if st.nontrivial_total and (st.nontrivial_acc or 0) < 1.0
    ]
    return sorted(stats, key=lambda st: st.nontrivial_acc)[:limit]


def _render_summary(name, input_path, n_rows, overlap, meta, methods,
                    metrics, gold_path, out_dir):
    L = [f"# Eval summary -- {name}", ""]
    L.append(f"- Input: `{input_path}` -- {n_rows} labels · KB `{meta.get('kb_version', '?')}`")
    L.append(
        f"- Validated-store overlap: **{overlap['exact']} exact** · "
        f"{overlap['sibling']} sibling · {overlap['unseen']} unseen "
        f"(store: {overlap['store_rows']} rows)"
    )
    L.append("  _Exact hits replay stored decodes: accuracy on them measures KB recall,"
             " not generalization._")
    L.append("")

    L.append("## Coverage")
    L.append("")
    decoded, n = meta["decoded"], meta["n"]
    method_txt = " · ".join(f"{m}: {c}" for m, c in sorted(methods.items())) or "none"
    L.append(f"- Outputs: **{decoded}/{n} ({_pct(decoded / n if n else None)})** -- {method_txt}")
    L.append(f"- Residue (labels with no output yet): **{meta['residue']}**")
    if meta["residue"]:
        L.append("- Next: run the /decode skill on this batch (fresh LLM call per residue"
                 " label, appended to outputs.jsonl), then re-score that file with"
                 " `--outputs runs/<id>/outputs.jsonl`.")
    L.append("")

    L.append("## Accuracy vs gold")
    L.append("")
    if metrics is None:
        L.append(f"- No gold file{f' at `{gold_path}`' if gold_path else ''} --"
                 " accuracy skipped (coverage + showcase only)."
                 " To create gold, see docs/EVALUATION.md.")
    else:
        cal = metrics["calibration"]
        integ = metrics["integrity"]
        L.append(f"- Gold: `{gold_path}` -- matched {metrics['n_matched']} rows")
        L.append(
            f"- Schema-valid **{_pct(metrics.get('schema_validity_rate'))}** · "
            f"exact-match **{_pct(metrics['exact_match_rate'])}** · "
            f"core-exact **{_pct(metrics['core_exact_rate'])}**"
        )
        if cal["brier"] is not None:
            L.append(f"- Calibration: Brier {cal['brier']:.3f} · ECE {cal['ece']:.3f}"
                     f" (n={cal['n']})")
        L.append(
            f"- Integrity: {len(integ['missing_in_outputs'])} gold missing from outputs · "
            f"{len(integ['extra_in_outputs'])} extra outputs · "
            f"{len(integ['duplicate_output_keys'])} duplicate keys"
        )
        weakest = _weakest_fields(metrics)
        if weakest:
            worst = " · ".join(
                f"`{st.path}` {_pct(st.nontrivial_acc)} ({st.nontrivial_total})"
                for st in weakest
            )
            L.append(f"- Weakest fields (gold non-null): {worst}")
        else:
            L.append("- Weakest fields: none -- every matched field correct")
        L.append("")
        L.append("Full breakdown: report.md · miss queue: errors.jsonl")
    L.append("")

    L.append("## Files")
    L.append("")
    L.append(f"`{out_dir}`: summary.md · coverage.md · showcase.md"
             + (" · report.md · report.json · errors.jsonl" if metrics is not None else ""))
    L.append("")
    return "\n".join(L)


def run_eval(input_path, out_dir=None, gold_path=None, outputs_path=None,
             schema_path=None, store_path=None, name=None):
    """Drive decode -> score -> showcase; write summary.md; return a result dict."""
    input_path = Path(input_path)
    name = name or input_path.parent.name
    rows = read_jsonl(input_path)
    overlap = store_overlap(rows, store_path)

    if outputs_path:
        # Score an existing outputs file (e.g. merged deterministic+LLM rows).
        outputs_path = Path(outputs_path)
        out_dir = Path(out_dir) if out_dir else outputs_path.parent
        outputs = read_jsonl(outputs_path)
        _, kb_version = build_context_pack()
        meta = {
            "decoder": f"pre-decoded ({outputs_path})",
            "kb_version": kb_version,
            "input": str(input_path),
            "n": len(rows),
            "decoded": len(outputs),
            "residue": max(0, len(rows) - len(outputs)),
        }
    else:
        if out_dir is None:
            _, kb_version = build_context_pack()
            out_dir = repo_root() / "runs" / f"{name}_eval_{kb_version}"
        out_dir = Path(out_dir)
        meta = deterministic_batch.run(input_path, out_dir, schema_path, store_path)
        outputs = read_jsonl(out_dir / "outputs.jsonl")

    methods = Counter(r.get("decode_method") or "unspecified" for r in outputs)

    metrics = None
    gold_path = Path(gold_path) if gold_path else None
    if gold_path and gold_path.exists():
        gold = read_jsonl(gold_path)
        metrics, _alignment, schema_invalid = score(outputs, gold, schema_path)
        write_score_reports(out_dir, metrics, schema_invalid)

    showcase_md = render_showcase(outputs, run_meta=meta, schema_path=schema_path)
    (out_dir / "showcase.md").write_text(showcase_md, encoding="utf-8")

    summary_md = _render_summary(
        name, input_path, len(rows), overlap, meta, methods, metrics, gold_path, out_dir
    )
    (out_dir / "summary.md").write_text(summary_md, encoding="utf-8")
    return {
        "out_dir": out_dir,
        "overlap": overlap,
        "meta": meta,
        "metrics": metrics,
        "summary_md": summary_md,
    }


def main() -> int:
    configure_stdout_utf8()
    ap = argparse.ArgumentParser(
        description="Decode a batch, score it against gold (if any), render the "
                    "showcase, and print one summary."
    )
    ap.add_argument("--batch", help="batch id: data/eval/batches/<id>/input.jsonl "
                                    "+ tests/gold/<id>/gold.jsonl")
    ap.add_argument("--input", help="explicit input.jsonl (overrides the --batch convention)")
    ap.add_argument("--gold", help="explicit gold.jsonl (default: the --batch convention)")
    ap.add_argument("--outputs", help="score this existing outputs.jsonl instead of "
                                      "running the deterministic decoder")
    ap.add_argument("--out-dir", help="default: runs/<batch>_eval_<kb_version>, or the "
                                      "outputs file's directory with --outputs")
    ap.add_argument("--schema", help="schema path (defaults to schema/decoded_label.schema.json)")
    ap.add_argument("--store", help="validated-decodes store override (mainly for tests)")
    args = ap.parse_args()
    if not args.batch and not args.input:
        ap.error("give --batch <id> or --input <input.jsonl>")

    root = repo_root()
    input_path = Path(args.input) if args.input else (
        root / "data" / "eval" / "batches" / args.batch / "input.jsonl"
    )
    gold_path = Path(args.gold) if args.gold else (
        root / "tests" / "gold" / args.batch / "gold.jsonl" if args.batch else None
    )

    result = run_eval(
        input_path,
        out_dir=args.out_dir,
        gold_path=gold_path,
        outputs_path=args.outputs,
        schema_path=args.schema,
        store_path=args.store,
        name=args.batch,
    )
    print(result["summary_md"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
