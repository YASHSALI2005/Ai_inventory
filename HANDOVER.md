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

## Status — 2026-09-09

**Phase 0 approved. Phase 1 (POC) started — vertical slice is running end to end.**

Run it:

```
python cli.py build --preset toy     # generate + run engine   (~0.5s)
python cli.py score --preset toy     # grade against answer key
python -m pytest -q                  # 12 tests
```

| Step | State |
|---|---|
| `contracts/` schemas + config | Done. Cutoff date and the shortage-cost function live here |
| `sim/` replenishment mechanics | Done. Shared by generator and scoring |
| 1 · data generator + answer key | **Done at toy scale.** Not yet run at `--preset full` |
| 2 · data quality (cap 4) | **Negative stock only.** Six checks + duplicate matcher still to write |
| 3 · demand classifier | Not started |
| 4 · forecasters (cap 1) | Not started |
| 5 · stocking policy (cap 3) | Not started |
| 6 · dead money + transfers (caps 2, 5) | Not started |
| 7 · API + screens | Not started |
| 8 · chat (cap 7) | Not started |

**Current score** (`python cli.py score`): NEGATIVE_STOCK 1/1 found, 0 false alarms.
Thin because toy plants ~13 defects total; real scoring quality gets judged at
`--preset full`.

### Dataset properties, asserted in tests

Both inside their industry bands, and both **emergent** rather than injected:

- **35%** of lines idle for 24 months (band 30–50%)
- **36%** of stock value dead (band 20–40%)

If a change pushes either outside its band, `tests/test_generator.py` fails. That
is deliberate — every downstream number is measured against this data, so a
generator that drifts into producing a supermarket would make the forecasts and
the backtest look excellent and mean nothing.

## Next

1. Remaining rule checks in `engine/quality.py`, scoring after each one.
2. Duplicate matcher — TF-IDF candidates + RapidFuzz scoring. No embeddings
   (see `DECISIONS.md`); the interface takes a list of scorers so they can be added.
3. One dashboard screen, to close the vertical slice.
4. Then deepen step by step: classifier → forecasters → policy → dead money.
5. Run `--preset full` once and check the realism bands still hold at 20k items.

## Things to avoid

- **Never let `engine/` import `sim/`, `generator/` or `scoring/`.** A test parses
  the AST and fails if it does. If the engine could see the answer key, the score
  would be meaningless and nobody would notice until a Ma'aden engineer asked how
  it was measured.
- **Do not plant overstock, obsolescence or critical-below-reorder.** They must
  emerge from the stale policy and from equipment decommissioning, and are scored
  against `truth`. Planting them would grade the engine on our own injection rules.
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
