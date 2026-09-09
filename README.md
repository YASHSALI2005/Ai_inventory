# Ma'aden MRO Intelligence POC

AI-powered inventory intelligence and MRO optimization for Ma'aden Aluminium.
Response to SOW `MD-404-1000-OE-DG-SOW-0000_` Rev 0.0, Use Case 01.

**Status: Phase 0 — proposal complete, no code yet.**

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
