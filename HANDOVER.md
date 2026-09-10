# HANDOVER — Ma'aden MRO Intelligence POC

**Read this first.** Living status board, updated every session. Not a log — history lives
in git and `DECISIONS.md`.

## What this project is

Response to Ma'aden SOW `MD-404-1000-OE-DG-SOW-0000_` Rev 0.0, **Use Case 01 — AI-Powered
Inventory Intelligence & MRO Optimization**. A proof of concept on synthetic data.

**Scope was fixed on 2026-09-10 to three claims and nothing else** — see
[`IMPLEMENTATION-PLAN.md`](IMPLEMENTATION-PLAN.md), which is now the authority on what
gets built:

1. We can find data problems, measured against a sealed answer key.
2. We can set better stock levels than the plant's min/max, measured by backtest.
3. A planner can ask a question in English and get a checkable answer.

If a piece of work does not serve one of those three, it is out of scope. Explicitly
**not being built**: LightGBM, embedding-based matching, Arabic, login, SAP connection,
purchase orders, or any screen beyond the dashboard and the item view.

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
python cli.py all --preset full     # 20k materials                 (~33s)
python -m pytest -q                 # 143 tests
python cli.py serve --preset full   # the three screens
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
| 2 · data quality (cap 4) | **Done — all 7 checks + matcher.** 99% recall, 99% precision at full |
| 3 · classifier (ADI × CV²) | **Done.** Monthly periods, 97.6% agreement with `PROFILE_TO_SBC_CLASS` |
| 4 · forecast (Croston family) | **Done.** TSB for sparse, SES for the rest; MASE 0.84–0.87, all four beat naive |
| 5 · levels + backtest | **Done — headline number two.** Total cost −8% on the held-out year, with the service-level sweep and order quantities |
| 6a · dead money | Not started — scorer stubbed; engine figure goes beside truth on the dashboard |
| Screens | **Done — Dashboard · Storerooms · Stock board · Recommendations, Evidence in the footer.** Present mode, dark by default with a toggle, vendored JS, no CDN |
| 8 · chat, thin | Not started — four tools, twenty golden questions |
| 6b · transfers, slider, work queue | **Only if everything above is green** |

**Current score, full preset** — every planted defect type now has a check:

| Check | Planted | Found | Missed | False | Recall | Precision |
|---|---|---|---|---|---|---|
| BLANK_MPN | 262 | 262 | 0 | 0 | 100% | 100% |
| BLANK_UOM | 60 | 60 | 0 | 0 | 100% | 100% |
| DUPLICATE_MATERIAL | 140 | 134 | 6 | 19 | **96%** | **88%** |
| IMPOSSIBLE_LEAD_TIME | 60 | 60 | 0 | 0 | 100% | 100% |
| ISSUE_WITHOUT_WORK_ORDER | 594 | 594 | 0 | 0 | 100% | 100% |
| NEGATIVE_STOCK | 100 | 100 | 0 | 0 | 100% | 100% |
| UOM_MISMATCH | 80 | 69 | 11 | 0 | 86% | 100% |
| **Total** | **1,296** | **1,279** | **17** | **19** | **99%** | **99%** |

LEDGER_MISMATCH raises 100 informational findings, excluded from precision.

Two known limits, both measured rather than assumed:
- **UOM_MISMATCH** catches an item swapped into a *rare* unit, never one swapped
  into its group's dominant unit — all 11 misses are that shape.
- **Duplicates** lose most to `token_dropped` (72%): when the size is simply left
  off the re-keyed record there is little left to match on. `token_front` and
  `abbrev` are at 98-100%.

### Dataset properties — all asserted in tests, all measured by `scoring/dataset_report.py`

The report is the single place these are computed, so the console and the test
suite cannot disagree about what "in band" means.

| Property | Toy | Full | Target |
|---|---|---|---|
| Lines idle >24 months | 35% | 35% | 30–50% |
| Stock value dead | 15% | 29% | 20–40% at full; wide sanity range at toy |
| Shutdown issue-rate multiple | 3.1× | 3.5× | ≥3× baseline |
| Issues per work order | 1.85 | 1.99 | ≥1.5 |
| Planned WOs raised in advance | 100%, 37d median | 100%, 38d | 100% |
| Unexplained ledger mismatches | 0 | 0 | 0 |
| Unplanted negative balances | 0 | 0 | 0 |
| Materials in >1 storeroom | 20% | 17% | ≥10% |
| Descriptions repeated outside planted copies | 0 | 0 | 0 |

Idle share, dead money, overstock, obsolescence and stockouts are all **emergent**
— they come from the stale min/max policy running against drifting demand and from
equipment being decommissioned mid-history. Only *data* defects are planted.

> **Dead value is asserted at full scale only.** It is a value-weighted share, so at
> 300 materials a handful of expensive rows decide it: 15% on toy against 29% on
> full from the same generator, moving several points on any reshuffle of the random
> stream. Toy keeps a wide sanity range so a genuinely broken generator still fails
> there. Do not tune the generator to make toy land in the industry band — that is
> fitting to noise.

## The levels — how they are set now (2026-09-10, third pass)

Three rules, in this order, and the order matters:

1. **Service level is a policy, not an output.** `CostModel.target_service_level`
   is A 99% / B 95% / C 85%. The newsvendor fractile may only argue a level DOWN,
   for an expensive part where a year on the shelf is a real cost; it never raises
   it. Before this, every cheap part of every class sat at the 99.5% cap and C-class
   collapsed into A from the cheap side. Medians now: A 99.0%, B 95.0%, C 85.0%.
2. **Regularly-used parts (smooth, erratic) get their buffer from history**, not
   from a simulation: the quantile of what actually moved in every stretch of the
   same length as lead time + review over the two training years — several hundred
   real windows. Capped at three windows of expected demand.
3. **Rarely-used parts (intermittent, lumpy) keep the TSB simulation**, capped
   between the most the part ever needed in one window and twice that, aiming at
   three windows of expected demand.

Two things feed those rules and are easy to miss:

- **Outage demand is left out of the buffer.** Planned work issued to a plant while
  that plant is in a scheduled shutdown is the shutdown, and belongs on an order
  raised against the schedule — not in a permanent safety stock. Decided by the
  calendar, not the work-order tag: in the month that broke the rolling-mill filter,
  only 4,320 of 15,474 units were tagged SHUTDOWN. That order is not raised by this
  system yet, so the backtest charges us for shutdown shortages the schedule would
  have prevented. It is in the limits.
- **A pack has to repeat to be believed.** The modal receipt quantity counts as a
  pack only if it is at least half of a part's receipts and there are at least
  three of them. Under the plant's old min/max rule a receipt is "order-up-to minus
  whatever was left", which drifts every time; the first cut took that mode as a
  4,129-unit pack for a part used a thousand a month.

The filter that started this (M-016367, ~1,080/month, 74-day window): reorder point
20,089 and "Order 32,630" became **12,434** and **Order 9,999** — three windows of
expected demand, which is your own cap; the 99th percentile of its real windows is
honestly higher, and the reason string says so.
Two sanity tests hold on every position: regular movers ≤ 3× expected window
demand; every class ≤ 2× the historical maximum unless raised by the criticality
floor.

### One more data fix the screens exposed

No storeroom record may consume more than SAR 3m a year
(`DemandShaping.max_annual_consumption_sar`). The heavy-tailed popularity draw had
produced a SAR 6,142 drill bit used eighty a day — 57% of the plant's consumption
value in the top 1% of records, and "SAR 97m to bring one part back to level".
Applied as a scaling after every random draw, so it moves no other position's
parameters.

## Headline number two — the backtest, full preset

| | plant's min/max | ours | change |
|---|---|---|---|
| Days waiting for a part | 855,161 | 454,486 | **-47%** |
| Units short | 593,970 | 319,974 | **-46%** |
| Capital on the shelf | SAR 1,376.5m | SAR 1,759.9m | **+28%** |
| Cost of being short | SAR 1,377.3m | SAR 661.1m | -52% |
| Cost of holding | SAR 344.1m | SAR 440.0m | +28% |
| Cost of placing orders | SAR 31.7m | SAR 41.6m | +31% |
| **All three together** | **SAR 1,753.2m** | **SAR 1,142.7m** | **-35%** |
| Orders placed | 35,205 | 46,241 | +31% |

Capital went +71% → **+28%** with the levels fix, days waiting
still -47%. Orders are up because the fake 4,129-unit packs are
gone; the order quantity is now one window of expected demand, and ordering is
priced in the total. The frontier has a real interior optimum near 99% service now;
the plant still sits off its low end (`plant_below_the_sampled_range`),
so "less capital at their service level" remains unavailable and the report says so.

**The planner's numbers** — full preset: 8,446 parts need action,
**SAR 628.6m to bring them back to level** (shortfall below the
reorder point — NOT the whole order, which is SAR 956.5m across
7,288 orders and lives on the Recommendations page);
3,024 critical parts below level, SAR 326.4m;
60 moves saving SAR 6.2m of buying.

## The screens — round 3 and 4

`python cli.py serve --preset full`. Four pages in the nav, in presentation order,
plus **Evidence** as a footer link. **Present** (button in the nav) hides the nav,
enlarges type, walks the four pages with ← → and shows "n / 4"; Escape exits.
**Dark by default**, with a light/dark toggle in the nav and in the present-mode
HUD; the choice is kept in `localStorage` and nowhere else.

- **Dashboard** — stock value, dead money, critical parts below level, waiting-days
  improvement; then four inline-SVG charts: value by store, demand-class mix by
  store (stacked), plant-wide monthly usage with the forecast laid over the held-out
  year, and the frontier with both policies. A date line under the title.
- **Storerooms** — one card per store (value, parts, idle share, none-left count,
  top five by value, top five to act on); click → that store's parts, one line
  each; below, "stock that could be moved" with SAR saved vs buying.
- **Stock board** — as before plus a sparkline per row and, for anything below its
  level, "Order by" (Now if already late) with "runs out around" underneath.
- **Recommendations** — three tabs ranked by money with totals: Order (part, qty,
  order-by, cost, reason), Move (from → to, qty, saved), Write off / review (says
  "coming with the dead-money step"). "Export to Excel" is a CSV with a byte-order
  mark from `/api/recommendations/{orders,moves}.csv` — .xlsx would mean a new
  dependency for the same outcome.
- **Drawer** — what to do first (accent), stat row, chart with the forecast over the
  tested year, "why this number" in a quiet panel at the bottom.

**The forecast on screen is the held-out year, not next year.** The date line says
"forecast Sep 2025 – Aug 2026, laid over what actually happened". A forward forecast
(Sep 2026 – Aug 2027) would need a refit on all 36 months; not built, and saying it
is would be a lie the chart could not support.

**If the board shows an error, restart the server.** `cli.py serve` keeps the API
module in memory while the page is read from disk on every request; a server started
before an API change serves a page that asks for fields it does not have. The page
now says so instead of crashing, and an older `positions.parquet` degrades to blank
columns rather than a 500.

## Next — step 6a, dead money

1. Engine computes its own dead-money list from step 5's justified quantity plus
   obsolescence inferred from equipment status and demand cessation. Ranked in SAR
   at SAP moving average.
2. Scored against `truth`: SAR found / true / wrongly flagged; obsolete
   found / missed / falsely flagged. Engine figure sits beside the truth figure.
3. Then the thin chat (four tools, twenty golden questions). The scenario slider
   now has its data (`results/frontier.json`); transfers and the work queue only
   if everything above is green.

Full order and the exclusions are in [`IMPLEMENTATION-PLAN.md`](IMPLEMENTATION-PLAN.md).

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
- **Service level is a policy.** `target_service_level` is the band; the
  arithmetic only lowers. Do not let a cost model raise a C part to 99.5%.
- **Regular movers are buffered from history, rare movers from simulation, and
  both are capped.** Uncapped bootstrap quantiles produced eighteen months of
  supply on a two-month-lead part.
- **Shutdown demand is not buffer.** It is decided by the calendar, not the tag.
- **One shortage cost, used everywhere.** `CostModel.shortage_cost_per_unit`
  feeds the service level, the board's ranking and the backtest. Two versions
  of it optimises for one objective and marks against another.
- **Do not price a shortage as a multiple of unit price.** Downtime is a
  property of the equipment, not of the part.
- **Do not tune `holding_rate_per_year` or `expedite_premium` to make capital
  fall.** They are the plant's assumptions and they decide the answer.
- **Never let a screen calculate.** The API reads `results/positions.parquet` and
  filters it. A page that recomputes will disagree with the scoreboard beside it,
  and will stall on 25,000 positions while somebody is watching.
- **No CDN, ever.** A demo laptop on a plant site may have no route out.
  `tests/test_screens.py` fails on any remote `src` or `href`.
- **Never let the two backtest policies draw their own lead times.** They share one
  pre-drawn matrix (`sim.replenish.walk(lead_time_draws=…)`). Separate draws make
  part of any improvement luck, and nothing in the output would show it.
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
