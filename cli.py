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
    from engine import quality

    cfg = _cfg(args)
    if not (cfg.source_dir / "stock.parquet").exists():
        print("no dataset — run `build` first", file=sys.stderr)
        return 1

    t0 = time.time()
    findings = quality.run(cfg)
    by_type = findings.defect_type.value_counts().to_dict()
    print(f"engine: {len(findings):,} findings   ({time.time() - t0:.1f}s)")
    for k, v in sorted(by_type.items()):
        print(f"  {k:<26} {v:>6}")
    return 0


def cmd_score(args) -> int:
    from scoring import defects

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

    print(
        f"run {manifest['config_hash']} · seed {manifest['seed']} · "
        f"git {manifest['git_sha']} · cutoff {manifest['cutoff_date']}"
    )
    print()
    print(defects.render(scores, summary))

    print()
    print("emergent problems (scored against truth, not a planted list):")
    for name, fn in (
        ("dead money", defects.score_dead_money),
        ("obsolete", defects.score_obsolete),
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


def cmd_all(args) -> int:
    for fn in (cmd_build, cmd_run):
        rc = fn(args)
        if rc:
            return rc
        print()
    return cmd_score(args)


def cmd_serve(args) -> int:
    print("serve lands in step 7", file=sys.stderr)
    return 1


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
        ("all", cmd_all, "build, run, score"),
        ("serve", cmd_serve, "run the API"),
    ):
        sub.add_parser(name, parents=[common], help=helptext).set_defaults(fn=fn)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
