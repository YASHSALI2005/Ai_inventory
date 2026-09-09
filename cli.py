"""
Pipeline entry point: build -> score -> serve.

Everything is batch. The engine writes result Parquet plus a run manifest; the API
only ever reads what is already on disk. Nothing is computed while a demo is
being clicked through.

    python cli.py build --preset toy
    python cli.py score --preset toy
    python cli.py serve --preset toy      (from step 7)
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from contracts import schemas as S
from contracts.config import RunConfig


def _cfg(args) -> RunConfig:
    return RunConfig.load(getattr(args, "config", None), preset=args.preset, seed=args.seed)


def cmd_build(args) -> int:
    import generator
    from engine import quality

    cfg = _cfg(args)
    t0 = time.time()
    print(f"generating [{cfg.preset}] seed={cfg.seed} cutoff={cfg.cutoff_date} ...")
    g = generator.generate(cfg)
    manifest = generator.write(cfg, g)
    print(
        f"  {manifest['n_materials']:,} materials  "
        f"{manifest['n_movements']:,} movements  "
        f"{manifest['n_planted_defects']:,} planted defects   ({time.time() - t0:.1f}s)"
    )

    t1 = time.time()
    print("running engine: data quality ...")
    findings = quality.run(cfg)
    print(f"  {len(findings):,} findings   ({time.time() - t1:.1f}s)")

    print(f"\nwrote  {cfg.source_dir}")
    print(f"       {cfg.answer_key_dir}   (engine never reads this)")
    print(f"       {cfg.results_dir}")
    return 0


def cmd_score(args) -> int:
    from scoring import defects

    cfg = _cfg(args)
    manifest_path = cfg.results_dir / S.RUN_MANIFEST_FILE
    if not manifest_path.exists():
        print("nothing to score — run `build` first", file=sys.stderr)
        return 1

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scores, summary = defects.score(cfg)

    print(f"run {manifest['config_hash']} · seed {manifest['seed']} · "
          f"git {manifest['git_sha']} · cutoff {manifest['cutoff_date']}")
    print()
    print(defects.render(scores, summary))
    return 0


def cmd_serve(args) -> int:
    print("serve lands in step 7", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    # shared options live on a parent so they work either side of the subcommand:
    # `cli.py build --preset toy` is what anyone will type first
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--preset", default="toy", choices=("toy", "full"))
    common.add_argument("--seed", type=int, default=RunConfig().seed)
    common.add_argument("--config", default=None, help="optional YAML overriding RunConfig")

    p = argparse.ArgumentParser(prog="mro", description=__doc__, parents=[common])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build", parents=[common], help="generate data and run the engine").set_defaults(
        fn=cmd_build
    )
    sub.add_parser(
        "score", parents=[common], help="grade the engine against the answer key"
    ).set_defaults(fn=cmd_score)
    sub.add_parser("serve", parents=[common], help="run the API").set_defaults(fn=cmd_serve)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
