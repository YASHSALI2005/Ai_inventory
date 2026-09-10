"""
Pipeline entry point: build -> run -> score -> serve.

The stages are separate on purpose. `build` writes the dataset and the answer key;
`run` executes the engine and must never touch `answer_key_dir`; `score` opens the
answer key and grades what `run` produced; `serve` only reads results.

    python cli.py build --preset toy
    python cli.py run   --preset toy
    python cli.py score --preset toy
    python cli.py all   --preset toy     # chains the three, scoreboard last
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from contracts import schemas as S
from contracts.config import RunConfig


def _cfg(args) -> RunConfig:
    extra = {}
    if getattr(args, "data_dir", None):
        extra["data_dir"] = Path(args.data_dir)
    return RunConfig.load(
        getattr(args, "config", None), preset=args.preset, seed=args.seed, **extra
    )


def cmd_build(args) -> int:
    import generator
    from scoring import dataset_report

    cfg = _cfg(args)
    t0 = time.time()
    print(f"building [{cfg.preset}] seed={cfg.seed} cutoff={cfg.cutoff_date} ...")
    g = generator.generate(cfg)
    m = generator.write(cfg, g)
    print(
        f"  {m['n_materials']:,} materials  {m['n_positions']:,} positions  "
        f"{m['n_movements']:,} movements  {m['n_work_orders']:,} work orders  "
        f"{m['n_planted_defects']:,} planted   ({time.time() - t0:.1f}s)"
    )
    print()
    print(dataset_report.render(dataset_report.measure(cfg)))
    return 0


def cmd_run(args) -> int:
    """The engine. Reads source tables only — never the answer key."""
    from engine import classify, dead_money, forecast, levels, positions, quality

    cfg = _cfg(args)
    if not (cfg.source_dir / "stock.parquet").exists():
        print("no dataset — run `build` first", file=sys.stderr)
        return 1

    t0 = time.time()
    findings = quality.run(cfg)
    by_type = findings.defect_type.value_counts().to_dict()
    print(f"engine, data quality: {len(findings):,} findings   ({time.time() - t0:.1f}s)")
    for k, v in sorted(by_type.items()):
        print(f"  {k:<26} {v:>6}")

    t1 = time.time()
    result = classify.run(cfg)
    mix = result.report["class_mix"]
    print(f"engine, demand classes: {len(result.per_position):,} positions   "
          f"({time.time() - t1:.1f}s)")
    for k in S.DEMAND_CLASS:
        n = mix.get(k, 0)
        print(f"  {k:<26} {n:>6}  ({n / max(len(result.per_material), 1):.0%})")

    t2 = time.time()
    fc = forecast.run(cfg)
    print(f"engine, forecast: {fc.report['horizon_months']} months ahead   "
          f"({time.time() - t2:.1f}s)")
    print(f"  {'class':<14}{'positions':>10}{'method':>28}"
          f"{'ours':>8}{'naive':>8}{'zero':>8}")
    for row in fc.report["mase_by_class"]:
        print(f"  {row['class']:<14}{row['positions']:>10,}{row['method']:>28}"
              f"{row['mase']:>8.2f}{row['naive']:>8.2f}{row['zero']:>8.2f}")
    beat = fc.report["classes_beating_both_baselines"]
    print(f"  beats both baselines: {', '.join(beat) if beat else 'none'}")

    t3 = time.time()
    lv = levels.run(cfg)
    print(f"engine, stock levels: {lv.report['positions']:,} positions   "
          f"({time.time() - t3:.1f}s)")
    sl = lv.report["service_level_by_criticality"]
    print("  service level from each item's own economics — a range now, not one "
          "figure per class, because an expensive spare costs more to hold than a "
          "cheap one while the stoppage it prevents costs the same:")
    for k in sorted(sl):
        v = sl[k]
        print(f"    {k}  median {v['median']:.1%}   "
              f"{v['low']:.1%}-{v['high']:.1%}   ({v['positions']:,} records)")

    t4 = time.time()
    pos = positions.run(cfg)
    print(f"engine, position file for the screens: {len(pos):,} rows   "
          f"({time.time() - t4:.1f}s)")
    for band, n in pos["band"].value_counts().items():
        print(f"  {band:<26} {n:>6}")

    t5 = time.time()
    dead = dead_money.run(cfg)
    print(f"engine, dead money: {len(dead):,} positions flagged, "
          f"SAR {dead['dead_value_sar'].sum():,.0f}   ({time.time() - t5:.1f}s)")
    for k, g in dead.groupby("category"):
        print(f"  {k:<26} {len(g):>6}   SAR {g['dead_value_sar'].sum():>15,.0f}")
    return 0


def cmd_score(args) -> int:
    from scoring import backtest, classifier, defects, frontier

    cfg = _cfg(args)
    manifest_path = cfg.results_dir / S.RUN_MANIFEST_FILE
    if not manifest_path.exists():
        print("nothing to score — run `build` first", file=sys.stderr)
        return 1
    if not (cfg.results_dir / S.IMPLEMENTED_CHECKS_FILE).exists():
        print("engine has not run — run `run` first", file=sys.stderr)
        return 1

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scores, summary = defects.score(cfg)
    classifier_result = classifier.score(cfg)
    # headline figures are written here, once, so the dashboard computes nothing
    from scoring import summary as summary_writer

    summary_writer.build(cfg)

    print(
        f"run {manifest['config_hash']} · seed {manifest['seed']} · "
        f"git {manifest['git_sha']} · cutoff {manifest['cutoff_date']}"
    )
    print()
    print(defects.render(scores, summary))

    misses = defects.duplicate_miss_report(cfg)
    if misses:
        print()
        print(defects.render_duplicate_misses(misses))

    if classifier_result.get("status") != "not_implemented":
        print()
        print("demand classes, graded against how the plant really behaves:")
        print(classifier.render(classifier_result))

    if (cfg.results_dir / "levels.parquet").exists():
        bt = backtest.run(cfg)
        print()
        print("stock levels replayed against the plant's own, same year same demand:")
        print(backtest.render(bt))
        fr = frontier.run(cfg)
        print()
        print("the same year at every service level — the trade, priced:")
        print(frontier.render(fr))

    print()
    print("emergent problems (scored against truth, not a planted list):")
    dm = defects.score_dead_money(cfg)
    if dm.get("status") == "scored":
        print(defects.render_dead_money(dm))
        (cfg.results_dir / "dead_money_score.json").write_text(
            json.dumps(dm, indent=2), encoding="utf-8")
    else:
        print(f"  dead money                 not implemented yet   {dm}")
    for name, fn in (
        ("critical below justified", defects.score_critical_below_rop),
    ):
        r = fn(cfg)
        if r.get("status") == "not_implemented":
            detail = ", ".join(f"{k}={v:,.0f}" if isinstance(v, float) else f"{k}={v}"
                               for k, v in r.items() if k != "status")
            print(f"  {name:<26} not implemented yet   ({detail})")
        else:
            print(f"  {name:<26} {r}")
    return 0


def cmd_report(args) -> int:
    """Rebuild the progress document from results/. Never hand-edited."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from docs.progress.make_progress_docx import build_document

    cfg = _cfg(args)
    try:
        out = build_document(cfg)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"progress document: {out}  ({out.stat().st_size / 1024:.0f} KB)")
    from docs.make_sheets import build as build_sheets

    for sheet in build_sheets(cfg):
        print(f"regenerated: {sheet.relative_to(Path(__file__).resolve().parent)}")
    return 0


def cmd_all(args) -> int:
    for fn in (cmd_build, cmd_run):
        rc = fn(args)
        if rc:
            return rc
        print()
    rc = cmd_score(args)
    if rc:
        return rc
    print()
    return cmd_report(args)


def cmd_serve(args) -> int:
    """Serve the dashboard. Reads results/ only — recomputes nothing."""
    from api.chat import load_dotenv
    from api.chat import status as chat_status

    load_dotenv()
    st = chat_status()
    print("assistant: " + (f"{st['provider']} · {st['model']}" if st["available"]
                          else f"unavailable — set {st['key_var']} in .env or the environment"))
    import threading
    import webbrowser

    try:
        import uvicorn

        from api.app import create_app
    except ImportError:
        print(
            "the API extras are not installed. Run:\n"
            '  python -m pip install "fastapi>=0.115" "uvicorn[standard]>=0.30"',
            file=sys.stderr,
        )
        return 1

    from scoring.summary import SUMMARY_FILE

    cfg = _cfg(args)
    if not (cfg.results_dir / SUMMARY_FILE).exists():
        print(
            f"no results to serve — run `python cli.py all --preset {cfg.preset}` first",
            file=sys.stderr,
        )
        return 1

    url = f"http://{args.host}:{args.port}"
    print(f"serving [{cfg.preset}] at {url}   (ctrl-c to stop)")
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(cfg), host=args.host, port=args.port, log_level="warning")
    return 0


def main(argv: list[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--preset", default="toy", choices=("toy", "full"))
    common.add_argument("--seed", type=int, default=RunConfig().seed)
    common.add_argument("--config", default=None, help="optional YAML overriding RunConfig")
    common.add_argument("--data-dir", default=None,
                        help="write datasets and results here instead of ./data")

    p = argparse.ArgumentParser(prog="mro", description=__doc__, parents=[common])
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn, helptext in (
        ("build", cmd_build, "generate the dataset and the answer key"),
        ("run", cmd_run, "execute the engine over the dataset"),
        ("score", cmd_score, "grade the engine against the answer key"),
        ("report", cmd_report, "rebuild the progress document from results"),
        ("all", cmd_all, "build, run, score, report"),
        ("serve", cmd_serve, "run the API"),
    ):
        parser = sub.add_parser(name, parents=[common], help=helptext)
        parser.set_defaults(fn=fn)
        if name == "serve":
            parser.add_argument("--host", default="127.0.0.1")
            parser.add_argument("--port", type=int, default=8000)
            parser.add_argument("--no-browser", action="store_true",
                                help="do not open a browser window")

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
