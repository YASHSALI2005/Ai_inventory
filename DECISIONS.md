# DECISIONS — Ma'aden MRO Intelligence POC

Append-only. One entry per meaningful decision or explicit approval, with the *reasoning*.
Never edit or delete an entry — a reversal gets a new entry that links back.

---

## 2026-09-09 — Build the POC on synthetic data, not client data
Model: Opus 5
Type: decision
Reasoning: Client instruction was to produce our own dummy data. It also removes the
           NDA / data-access dependency entirely, lets Phase 1 start immediately, and — the
           part that actually matters — lets us plant known defects and keep an answer key,
           so the POC can be *scored* rather than merely demonstrated.
Rejected: Waiting for a sanitized ERP extract (blocks start, and gives no ground truth to
          measure detection accuracy against)
Reverses: —

---

## 2026-09-09 — Synthetic generator must emit a ground-truth answer key
Model: Opus 5
Type: decision
Reasoning: A generator producing clean random data gives the AI nothing to find, and a demo
           on it can only be judged on whether it "looks plausible". Planting duplicates,
           obsolete items, negative stock, blank part numbers and UOM errors — and recording
           each one — converts the demo into a measurement: defects found / planted, plus
           false positives. This is the entire credibility argument in PROPOSAL.md §10.
Rejected: Realistic-looking random data (cheaper, unfalsifiable)
Reverses: —

---

## 2026-09-09 — Two demand populations get two different methods
Model: Opus 5
Type: decision
Reasoning: MRO inventory is a few thousand high-value, long-lead insurance spares with
           effectively no demand history, plus tens of thousands of forecastable consumables.
           The textbook `z · σ · √LT` safety-stock formula assumes normally-distributed
           demand; it is reasonable for the consumables and quietly wrong for the insurance
           spares — which is exactly where the expensive mistakes live. Items are therefore
           classified by ADI and CV² (Syntetos-Boylan-Croston) and routed: empirical,
           non-parametric quantiles over the protection window for lumpy/intermittent items,
           and a criticality override that stocks a never-consumed insurance spare regardless
           of what its history says.
Rejected: One blanket formula across the portfolio — produces confident, well-formatted,
          incorrect numbers on the items that matter most, which is worse than no system
Reverses: —

---

## 2026-09-09 — LLM narrates, never computes
Model: Opus 5
Type: decision
Reasoning: The conversational layer translates a question into a call against the analytics
           engine and reads back the structured result, always showing the numbers and the
           underlying item list. It performs no arithmetic and generates no figures. A
           hallucinated stock quantity in front of the client is unrecoverable, and planners
           will not adopt a tool they have caught being wrong once.
Rejected: Letting the model reason numerically over retrieved rows
Reverses: —

---

## 2026-09-09 — Adapter layer between sources and intelligence
Model: Opus 5
Type: decision
Reasoning: The synthetic generator sits behind the same interface a real SAP / PiLog
           connector would implement. This makes the answer to the inevitable management
           question — "how long before this runs on our real data?" — "replace one layer",
           not "rebuild it". The POC is built to be promoted to pilot, not thrown away.
Rejected: Wiring the generator directly into the analytics layer (faster now, forces a
          rewrite at Phase 2)
Reverses: —

---

## 2026-09-09 — Quote the conservative 20–40% SLOB benchmark, with its caveat
Model: Opus 5
Type: decision
Reasoning: The widely circulated "50–60% of MRO inventory is excess, obsolete or slow-moving"
           figure has no locatable primary study behind it; it traces to consultant estimates
           from self-selected engagements. Using it risks a domain expert in the room
           puncturing the whole deck. The 20–40% band is supportable, and stating the caveat
           ourselves buys more credibility than the larger number buys urgency.
Rejected: The 50–60% figure (bigger headline, indefensible under questioning)
Reverses: —

---

## 2026-09-09 — All seven capabilities shown; three built deep
Model: Opus 5
Type: decision
Reasoning: A demo omitting a capability invites "so it doesn't do number five?" A demo where
           all seven are shallow reads as a mockup. Depth goes where the money and the
           technical credibility are: SLOB/duplicate detection (largest cash release),
           reorder-point optimization (the defensible algorithm), conversational interface
           (the demonstration moment). Capability 6 is explicitly labelled as a simplified
           interactive model rather than presented as production logic.
Rejected: Three capabilities only (invites scope doubt); all seven equally deep (not
          achievable at POC scale, and dilutes the two that sell it)
Reverses: —

---

## 2026-09-09 — noah-stock-v2 is reference only; new project, free choice of stack
Model: Opus 5
Type: decision
Reasoning: Explicit client-side instruction. The prior project's par engine solved a genuinely
           analogous problem (a 52.6%-lumpy retail portfolio, handled with empirical
           distributions rather than the bell-curve formula) and that *design* transfers
           directly to MRO, which is lumpier still. The code does not: it has no MRO
           entities, no work orders, no equipment criticality, no LLM layer, and no
           migrations. We carry the ideas, not the repository.
Rejected: Forking it (imports retail-specific data model and its gaps)
Reverses: —

---

## 2026-09-09 — Parquet + DuckDB for the POC, not PostgreSQL
Model: Opus 5
Type: reversal
Reasoning: The client-facing build plan proposed PostgreSQL. For a few million rows
           a database server is setup and maintenance cost with no benefit; Parquet
           files read through DuckDB give the same query speed with nothing to
           install, which matters when the demo has to run on someone else's laptop.
           A real server, if the pilot needs one, swaps in behind the adapter layer —
           which is what the adapter layer exists for, so this does not weaken any
           claim made to the client.
Rejected: PostgreSQL (operational weight the POC cannot justify)
Reverses: the stack table in docs/BUILD-PLAN.md §5

---

## 2026-09-09 — Sentence-embedding duplicate matching cut from the POC
Model: Opus 5
Type: decision
Reasoning: The duplicate matcher will ship with normalised text, TF-IDF character
           n-grams for candidate generation and RapidFuzz token-set scoring on
           structured attributes. Embeddings would add a model download, a GPU-or-slow
           choice, and a dependency whose behaviour a Ma'aden engineer cannot inspect
           — for a marginal recall gain on the small share of pairs where the words
           differ but the meaning does not. The scorer will show exactly what that
           share costs us in recall, which is a better argument for adding embeddings
           later than an assertion now.
           The matcher interface takes a list of candidate scorers, so embeddings drop
           in as one more scorer without restructuring.
Rejected: sentence-transformers in the POC (weight and opacity now, measurable gain later)
Reverses: —

---

## 2026-09-09 — Arabic descriptions cut from the POC dataset
Model: Opus 5
Type: decision
Reasoning: PiLog's multilingual handling is real and worth demonstrating eventually,
           but no POC capability reads the Arabic field — the duplicate matcher, the
           classifier and the policy engine all work off English descriptions and
           structured attributes. Generating it would add plausible-looking data that
           nothing consumes, which is worse than absent: it invites a question we
           would have to answer with "nothing uses that yet".
Rejected: bilingual descriptions in Phase 1 (no consumer for the field)
Reverses: docs/PROPOSAL.md §7 lists Arabic descriptions in the dataset shape

---

## 2026-09-09 — Item criticality comes from the part, not from its equipment
Model: Opus 5
Type: decision
Reasoning: The first generator assigned equipment criticality at random and had
           materials inherit it. That produced a criticality-B spare power
           transformer and criticality-A washers, and because dead-money valuation
           keys off criticality, a single mis-graded transformer accounted for SAR
           2.3m of apparent waste. Criticality now comes from the seed file's
           crit_bias — a transformer is A because it is a transformer — with a 12%
           jitter and an upgrade if the owning asset is A-rated. The equipment link
           still drives obsolescence, which is what it is actually good for.
Rejected: pure equipment inheritance (poisons every downstream money figure)
Reverses: —

---

## 2026-09-09 — Commissioning spares model dead money, sized in units not years
Model: Opus 5
Type: decision
Reasoning: The largest real source of MRO dead money is the spares package bought
           when the plant was built and never consumed — directly on-theme, since Ras
           Al Khair was commissioned 2013-15. First attempt sized the package in
           "years of demand" (6-40y), which on items with real turnover produced 2,188
           UPS batteries and 648 cathode blocks, and pushed dead money to 91% of stock
           value. It is now an absolute 1-4 units applied only to lumpy and insurance
           profiles, which is what a capital spares package actually contains.
           With this and the criticality fix, the toy dataset lands at 35% of lines
           idle for 24 months (industry band 30-50%) and 36% of value dead (band
           20-40%). Both are asserted in tests so the generator cannot drift out.
Rejected: cover-years sizing (produced quantities no storeroom has ever held)
Reverses: —
