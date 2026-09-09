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

**Phase 0 (Understanding & proposal): complete, pending management review.**

| Item | State |
|---|---|
| Company + industry research | Done — in `docs/PROPOSAL.md` §2, §3, §5 |
| SOW capabilities restated in plain language | Done — `docs/PROPOSAL.md` §4 |
| POC scope, depth per capability, out-of-scope boundary | Done — `docs/PROPOSAL.md` §6 |
| Synthetic dataset design | Designed, not built — `docs/PROPOSAL.md` §7 |
| Architecture | Designed, not built — `docs/PROPOSAL.md` §8 |
| Management deck (long form, read) | Published — `docs/deck.html` → https://claude.ai/code/artifact/c565ff58-d6ea-44b2-91a3-64fca887a8e6 |
| **Pitch deck (4 slides, present)** | Published — `docs/pitch.html` → https://claude.ai/code/artifact/c3d347ad-8ead-42e4-91c6-8d8fd60ed3cf |
| **Build plan (published doc)** | Published — `docs/build-plan.html` → https://claude.ai/code/artifact/2d0d30b3-41c0-4460-8160-b5537a378b35 |
| **Code** | **None written.** Deliberate — awaiting Phase 1 go-ahead |

## Blocked on

Management go/no-go on the Phase 0 proposal. No code until that lands.

## Next, when Phase 1 starts

In order — each step is useless without the one before it:

1. **Synthetic data generator first.** Everything downstream is judged by it. It must emit a
   **ground-truth answer key** of every planted defect, or the POC cannot be scored and the
   whole verification story in §10 collapses.
2. Demand classifier (Syntetos-Boylan-Croston: ADI × CV²) → routes each item to the right
   forecasting method. This is the two-populations split; it gates capabilities 1 and 3.
3. Stocking policy engine — empirical quantiles for lumpy/intermittent, criticality override
   for insurance spares.
4. SLOB / duplicate / transfer detection (capabilities 2 and 5).
5. API + UI.
6. Conversational layer last — it narrates what the engine computes, so it needs the engine.

## Things to avoid

- **Do not apply `z · σ · √LT` safety stock across the board.** It is wrong for the
  insurance-spare population, which is where the expensive errors are. See `DECISIONS.md`
  2026-09-09 entry and `docs/PROPOSAL.md` §3.
- **Do not let the LLM compute anything.** It calls the engine and narrates the result. A
  hallucinated stock figure in a client demo is unrecoverable.
- **Do not quote the "50–60% of MRO is SLOB" benchmark.** No traceable primary source. We use
  20–40%, with the caveat stated. See `DECISIONS.md`.
- `noah-stock-v2` / `noah-stock-ui-v2` in the parent folder are **reference only** — a prior
  retail/F&B inventory project. Read for design ideas; do not fork, do not import.

## Related docs

- [`docs/PROPOSAL.md`](docs/PROPOSAL.md) — the client-facing proposal (the substantive doc)
- [`docs/deck.html`](docs/deck.html) — published management deck, same content, presentation form
- [`DECISIONS.md`](DECISIONS.md) — why things are the way they are
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — system shape
- [`CONSTRAINTS.md`](CONSTRAINTS.md) — what must never happen here
