# HANDOVER — Ma'aden MRO Intelligence POC

**Read this first.** Living status board, updated every session. Not a log — history lives
in git and `DECISIONS.md`.

## What this project is

Response to Ma'aden SOW `MD-404-1000-OE-DG-SOW-0000_` Rev 0.0, **Use Case 01 — AI-Powered
Inventory Intelligence & MRO Optimization**. Build a proof of concept, on synthetic data,
demonstrating all seven SOW capabilities; three built deep.

Build plan in plain words (algorithms named): **[`docs/build-plan.html`](docs/build-plan.html)**
→ https://claude.ai/code/artifact/2d0d30b3-41c0-4460-8160-b5537a378b35 (source text: `docs/BUILD-PLAN.md`).
Client-facing scope, benchmarks and architecture: **[`docs/PROPOSAL.md`](docs/PROPOSAL.md)**.
Read it before touching anything — it is the agreed statement of what we are building and why.

## Status — 2026-09-10

**Phase 0 approved. Phase 1 (POC) in progress — vertical slice runs end to end at
both presets, and the dataset now survives review.**

Run it:

```
python cli.py all --preset toy      # build + engine + scoreboard   (~1s)
python cli.py all --preset full     # 20k materials                 (~14s)
python -m pytest -q                 # 51 tests
python -m ruff check .
```

Stages are separate on purpose: `build` writes the dataset and answer key, `run`
executes the engine and never touches `answer_key_dir`, `score` grades what `run`
produced. `--data-dir` redirects everything, which is how the CLI smoke test works.

| Step | State |
|---|---|
| `contracts/` schemas + config | Done. Cutoff date, cost model and dead-money rule live here |
| `sim/` replenishment | Done. Vectorised across items, stochastic lead time, shared by generator and scoring |
| 1 · generator + answer key | **Done, both presets.** Typed equipment, positions, shutdown overlay, real work orders |
| 2 · data quality (cap 4) | **2 of 8 checks.** Negative stock + ledger reconciliation |
| 3 · demand classifier | Not started |
| 4 · forecasters (cap 1) | Not started |
| 5 · stocking policy (cap 3) | Not started |
| 6 · dead money + transfers (caps 2, 5) | Scorers stubbed; detection not started |
| 7 · API + screens | Not started |
| 8 · chat (cap 7) | Not started |

**Current score, full preset:** NEGATIVE_STOCK 100/100 found, 0 false alarms.
LEDGER_MISMATCH raises 100 informational findings (excluded from precision — see
`DECISIONS.md`).

### Dataset properties — all asserted in tests, all measured by `scoring/dataset_report.py`

The report is the single place these are computed, so the console and the test
suite cannot disagree about what "in band" means.

| Property | Toy | Full | Target |
|---|---|---|---|
| Lines idle >24 months | 36% | 38% | 30–50% |
| Stock value dead | 30% | 28% | 20–40% |
| Shutdown issue-rate multiple | 3.9× | 3.5× | ≥3× baseline |
| Issues per work order | 2.3 | 2.7 | ≥2 |
| Planned WOs raised in advance | 100%, 37d median | 100%, 38d | 100% |
| Unexplained ledger mismatches | 0 | 0 | 0 |
| Unplanted negative balances | 0 | 0 | 0 |
| Materials in >1 storeroom | 18% | 17% | ≥10% |

Idle share, dead money, overstock, obsolescence and stockouts are all **emergent**
— they come from the stale min/max policy running against drifting demand and from
equipment being decommissioned mid-history. Only *data* defects are planted.

> The toy preset's dead-value share is noisy: at 300 materials it is dominated by a
> handful of expensive rows, so it moves several points on any RNG reshuffle. It is
> in band, but do not treat small movements there as signal — check `--preset full`,
> where 20k materials average it out.

## Next

1. Remaining six rule checks in `engine/quality.py`, scoring after each one.
2. Duplicate matcher — TF-IDF candidates + RapidFuzz scoring. No embeddings
   (see `DECISIONS.md`); the interface takes a list of scorers so they can be added.
   Note the matcher must handle split history: half the planted duplicates carry
   20–60% of the original's issues.
3. One dashboard screen, to close the vertical slice.
4. Then deepen step by step: classifier → forecasters → policy → dead money.

## Things to avoid

- **Never let `engine/` import `sim/`, `generator/` or `scoring/`.** A test parses
  the AST and fails if it does. If the engine could see the answer key, the score
  would be meaningless and nobody would notice until a Ma'aden engineer asked how
  it was measured.
- **Do not plant overstock, obsolescence or critical-below-reorder.** They must
  emerge from the stale policy and from equipment decommissioning, and are scored
  against `truth`. Planting them would grade the engine on our own injection rules.
- **Never write `stock.on_hand` by hand.** It is recomputed from the movement
  ledger, and negatives are planted last. Any balance not backed by movements shows
  up as a LEDGER_MISMATCH the engine is right to flag and we were wrong to create.
- **Never mix per-day and per-event costs in the newsvendor fractile.** That bug
  pinned every service level to the cap and silently disabled the whole idea.
- **`shortage_cost_per_unit` is defined once**, in `CostModel`. It feeds the
  service level, the SAR work-queue ranking and dead-money valuation. Three
  different versions is how a demo contradicts itself on stage.
- **Do not report "value idle for 24 months" as dead money.** That is 90% of stock
  value and it is wrong: insurance spares correctly sit still for years.
- **Fit on `cfg.train_slice()`, score on `cfg.eval_slice()`.** Never touch the
  movements frame directly for either.
- **Do not apply `z · σ · √LT` across the board** — wrong for the insurance-spare
  population, which is where the expensive errors are.
- **Do not let the LLM compute anything.** It calls the engine and narrates.
- **Do not quote the "50–60% of MRO is SLOB" benchmark.** No traceable source.
- **`noah-stock-v2` / `noah-stock-ui-v2` are reference only** — a prior project.
  Read for design ideas; do not fork, do not import.

## Related docs

- [`docs/PROPOSAL.md`](docs/PROPOSAL.md) — the client-facing proposal (the substantive doc)
- [`docs/deck.html`](docs/deck.html) — published management deck, same content, presentation form
- [`DECISIONS.md`](DECISIONS.md) — why things are the way they are
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — system shape
- [`CONSTRAINTS.md`](CONSTRAINTS.md) — what must never happen here
