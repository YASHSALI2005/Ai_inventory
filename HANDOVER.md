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
python -m pytest -q                 # 132 tests
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
| Screens | **Done — four pages plus the item drawer.** Plain English, tooltips on every label, vendored JS, no CDN |
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

## The cost model — rebuilt 2026-09-10, and it moved every number

Shortage cost used to be a multiple of unit price. Clicking through the board made
the flaw impossible to miss: a SAR 2.2M spare transformer and a SAR 4 gasket that
stop the same potline came out at the identical service level, and the transformer
was given a reorder point of six. **Downtime does not care what the part cost.**

    shortage cost per unit = downtime_cost_per_day[criticality] x expedite_days[criticality]
                             + expedite_premium x unit_price

`downtime_cost_per_day_sar` is A 30,000 / B 4,000 / C 100 and `expedite_days` is
7 / 14 / 21. Those are the loss attributable to **one unit of one part** being
unavailable for a day, not the cost of a whole-plant stoppage — the distinction is
load-bearing, because the backtest sums this over 24,989 records and 365 days.
Charging a real potline outage against each of 644,232 unit-shortages produced a
shortage bill of SAR 10bn against SAR 1.4bn of inventory, which is arithmetic, not
a finding. Calibrated so the shortage bill sits in the same order as the holding
bill.

**One shortage cost now, not two.** The fractile and the backtest were briefly
using different formulas, and it cost 13 points of measured improvement: the policy
was optimised against downtime and marked against a multiple of unit price, so it
held stock the marking scheme gave it no credit for and came out 8% *worse* than
the plant's own levels on total cost while cutting days waiting by 65%. Two cost
models is a way to lose an argument you are winning.
`shortage_cost_per_unit_day` is now `shortage_cost_per_unit / 30`, full stop.

### What it did to the service levels

They now vary with price *within* a criticality, which is the point:

| | SAR 100 | SAR 77,000 | SAR 2.2M |
|---|---|---|---|
| A — the plant stops | 99.5% | 99.1% | 95.0% |
| B — production slows | 99.5% | 97.2% | 94.3% |
| C — somebody waits | 99.5% | 94.3% | 94.1% |

The spare transformer's reorder point went from 6 to **2**; a SAR 60 gasket's went
to 264. That was the complaint and it is fixed.

**A property worth knowing before quoting these:** the expedite premium alone
(4 x price against holding at 25%/year) puts a floor of about 94% under every
part, whatever its criticality. So criticality now separates parts at the prices
where holding is a real cost, and stops separating them at the cheap end, where
everything is held to the cap because holding costs nothing. That is the correct
newsvendor answer, and it is also why the next number went the way it did.

## Headline number two — the backtest, full preset

| | plant's min/max | ours | change |
|---|---|---|---|
| Days waiting for a part | 854,171 | 309,958 | **−64%** |
| Units short | 644,232 | 276,189 | **−57%** |
| Capital on the shelf | SAR 1,412.7m | SAR 2,415.4m | **+71%** |
| Cost of being short | SAR 1,476.9m | SAR 645.4m | −56% |
| Cost of holding | SAR 353.2m | SAR 603.9m | +71% |
| Cost of placing orders | SAR 31.7m | SAR 31.2m | −2% |
| **All three together** | **SAR 1,861.8m** | **SAR 1,280.5m** | **−31%** |

**Capital went UP, not down, and further up than before the cost-model change
(+50% → +71%).** That was not the expectation and it is worth saying why rather
than burying it: pricing an expedite properly makes holding almost any part
worthwhile, so the new model stocks *more*, not less. It is the right answer to
the question "what does it cost to be short", and it is the wrong lever to pull if
the goal is releasing cash. The two levers that would move capital down are the
holding rate (25%/year) and the expedite premium (4x) — both are assumptions, both
belong to the plant, and neither should be quietly tuned to make a slide work.

**The cash release is dead money (step 6a), not stock levels.** The sweep says the
same thing from a different direction: the plant waits longer than our lowest
sampled service level manages while holding less capital than any point on the
curve, so there is no service level at which our levels need less capital than
theirs. Their policy is under-serving, not over-invested.

### The service-level sweep

Ten levels off one simulation, replayed on the same demand and lead-time draws,
written to `results/frontier.json` for the slider. Total cost falls monotonically
with service across the sampled range, which is another way of seeing that the
shortage side dominates.

### Order quantities

An order must cover at least the demand expected while it is in transit, rounds up
to the pack the plant already receives in (read off its own receipt history), and
costs SAR 900 to place. Orders placed are **−2%** against the plant's — the first
cut was +71%.

## The screens

`python cli.py serve --preset full` — four pages plus a drawer, vendored JS, inline
SVG, no CDN and no build step. Everything is read from `results/positions.parquet`
and `results/storeroom_report.json`, both written by `run`; the API filters and
pages and computes nothing.

- **Today** — three tiles and nothing else: money that will never come back, parts
  nobody has used in two years, critical parts below their safe level. Each carries
  a sentence saying what it means and what to do.
- **Stock board** — one row per part in one storeroom, most urgent first. The
  second column says what to do (`Order 622 EA` / `Stocked elsewhere` / `Below safe
  level` / `Review — obsolete?` / `Nothing needed`) and is the only column that has
  to be read. Headline is "N parts need action today, SAR X to bring them to level"
  — the SAR-at-risk figure is gone from the screen because it read as an absurdity.
- **Storerooms** — what each store holds, then the transfer panel: the same part
  spare in one store while another is below its level, with quantity and value.
  That is SOW capability 5, and the sending store only offers what it holds *above*
  its own level so nobody is stripped to fix somebody else.
- **How well it works** — the evidence page. Defect scoreboard, forecast table,
  backtest, and the frontier chart with the plant's own policy plotted off the end
  of the curve. **The only page allowed to say recall, MASE or TSB.**
- **Drawer** — what to do, then the plain-English paragraph, then the chart. In
  that order: the explanation earns the number, and the chart is evidence for the
  explanation rather than the other way round.

Every tile label and column header carries an ⓘ with a one-sentence meaning, every
page opens with a "How to read this page" line, and money is shown in SAR millions
to one decimal everywhere.

Routes are a contract — `#/board`, `#/storerooms`, `#/evidence` and
`#/board/{material}/{storeroom}` are what the progress document photographs.

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
