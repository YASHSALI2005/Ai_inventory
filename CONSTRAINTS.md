# CONSTRAINTS — Ma'aden MRO Intelligence POC

What must never happen in this project. **Check before anything destructive or
wide-reaching.** Permission to act is not permission to act on anything.

---

## Client and data

- **Never put real Ma'aden data in this repository.** The POC runs on synthetic data by
  design. If a real extract arrives later it goes in a gitignored location, never committed.
- **Never present a benchmark as a Ma'aden measurement.** Industry figures are labelled as
  industry figures, every time. The moment a borrowed number is read as a measured one, the
  whole deck becomes indefensible.
- **Never quote the "50–60% of MRO is SLOB" figure.** No traceable primary source. Use 20–40%
  with its caveat.
- **Never invent a savings number, a timeline, or a client system detail.** Open questions
  stay open questions on the last slide. An invented ERP version is worse than an
  unanswered one.

## The AI layer

- **The LLM never computes.** It calls the engine and narrates the result. No arithmetic over
  retrieved rows, no estimated figures, no "approximately".
- **Every AI answer shows its numbers and its item list.** An answer the planner cannot check
  is an answer they will stop trusting after the first error.
- **No automatic purchase orders, no ERP write-back.** The POC reads and recommends; a human
  decides. This boundary should survive into production above a value threshold.

## The other repositories

- **`noah-stock-v2` and `noah-stock-ui-v2` are reference only.** Read them for design ideas.
  Do not fork, do not import code, do not modify them, do not commit into them. They are a
  different client's project.

## Engineering

- **No new dependency without asking.** Especially in the intelligence layer, which should
  stay auditable — a domain expert must be able to follow the reorder-point calculation.
- **Never apply one safety-stock formula across the whole portfolio.** See `DECISIONS.md`.
  The classifier routes; the routing is not optional.
- **The ground-truth answer key never reaches the intelligence layer.** If the engine can see
  the planted defects, the score is meaningless and we will not notice until a client asks
  how it was measured.
- **Do not commit `.serena/` or `.claude/`.** Add to `.gitignore` on repo init.

## Scope

- **One logical change per request.** Do not fold an unrelated fix into requested work.
- **State the plan before implementing anything non-trivial.** Catch bad reasoning while it
  is a paragraph, not 200 lines of diff.
- **Do not start Phase 2 work during Phase 1.** Live integration, SSO and production volumes
  are explicitly out of POC scope and documented as such to the client.
