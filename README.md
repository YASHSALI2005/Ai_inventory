# Ma'aden Aluminium — AI-Powered Inventory Intelligence & MRO Optimization (POC)

**Status: POC complete (2026-09-10).** Three claims, each measured rather than asserted:

| Claim | Measured on the full preset |
|---|---|
| We can find data problems | **98% of planted faults found at 98% precision**, against a sealed answer key the engine never reads |
| We can set better stock levels | **56% fewer days waiting for parts**, all costs together -36%, holding +28% more stock — the last year replayed under both sets of levels |
| We can find the dead money | **SAR 382.8m of SAR 391.7m truly dead (98%), 99% precision**, one reason per record |

The plant is invented, the faults were planted, and the answer key is sealed; Phase 1
swaps the generator for the SAP/PiLog extract behind the same interface.

## Run it

```
python -m pip install -e ".[engine,report,api,dev]"     # + [chat] for the assistant
python cli.py all --preset full        # build → run → score → report   (~4 min)
python cli.py serve --preset full      # the screens, http://127.0.0.1:8000
python -m pytest -q                    # the suite
```

Five pages in the nav — Dashboard · Storerooms · Stock board · Recommendations · Ask —
with Evidence in the footer. **Present** in the nav walks them for a meeting. The
assistant needs `ANTHROPIC_API_KEY` in the environment or in a git-ignored `.env` next to
`cli.py` (an OpenRouter key works too — recognised by its `sk-or-` prefix); without one the
page says so and everything else works.

## Run it with Docker

```
docker compose up --build      # http://localhost:8000
```

First start builds the `full` preset (~4 min) and caches it under `./data` (bind-mounted,
survives restarts); later starts skip straight to serving. Pass a different preset via the
image `CMD`, e.g. `docker run -p 8000:8000 -v ./data:/app/data maaden-mro-poc toy`. Set
`ANTHROPIC_API_KEY` in the shell environment before `docker compose up` to enable the
assistant — same "unavailable" fallback as running it bare.

## Read first

- [`HANDOVER.md`](HANDOVER.md) — status, what is done, what to avoid. **Start here.**
- [`docs/RESULTS-SHEET.md`](docs/RESULTS-SHEET.md) — one page: the three numbers, the backtest, the dead-money score, the limits. Regenerated from `results/`.
- [`docs/DEMO-SCRIPT.md`](docs/DEMO-SCRIPT.md) — the ten-minute click-through. Regenerated from `results/`.
- [`docs/progress/POC-PROGRESS.docx`](docs/progress/POC-PROGRESS.docx) — the progress document, screenshots included. `python cli.py report` rebuilds all three.
- [`DECISIONS.md`](DECISIONS.md) — why things are the way they are, including what was tried and reversed.
- [`ARCHITECTURE.md`](ARCHITECTURE.md) · [`CONSTRAINTS.md`](CONSTRAINTS.md) · [`docs/reference/UX-NOTES.md`](docs/reference/UX-NOTES.md)

## The rules that hold it together

`engine/` never reads `answer_key/`; `scoring/` grades it afterwards. The screens and the
assistant read `results/` and compute nothing. Every recommendation carries a reason a
planner can argue with. The assistant never does arithmetic. No new library without a
reason in DECISIONS.md.

## Read these first, in order

| File | What it is |
|---|---|
| **[HANDOVER.md](HANDOVER.md)** | **Start here.** Current status, what's next, what to avoid |
| [docs/PROPOSAL.md](docs/PROPOSAL.md) | The client-facing proposal — problem, research, scope, architecture, verification |
| [DECISIONS.md](DECISIONS.md) | Why things are the way they are. Append-only |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System shape |
| [CONSTRAINTS.md](CONSTRAINTS.md) | What must never happen here. Check before anything wide-reaching |

`docs/deck.html` is the published management deck — same content as the proposal, in
presentation form.

## What this is

Ma'aden Aluminium runs a fully integrated chain — bauxite mine, 600 km rail, alumina
refinery, smelter, rolling mill. Its MRO storeroom shows the standard pattern: capital frozen
in parts that will never be issued, while critical spares still run short.

The POC proves, on a synthetic dataset with deliberately planted defects and a ground-truth
answer key, that the dead capital can be identified and the critical parts better protected —
and it reports a measured score rather than a claim.

## Note on the neighbouring folders

`../noah-stock-v2` and `../noah-stock-ui-v2` are a **prior, unrelated project** kept for
reference only. Do not fork or modify them.
