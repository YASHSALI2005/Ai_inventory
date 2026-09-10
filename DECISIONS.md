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

---

## 2026-09-10 — Newsvendor inputs were in mismatched units; fractile was dead
Model: Opus 5
Type: reversal
Reasoning: Shortage cost was expressed per unit-DAY and holding cost per unit-DAY,
           giving a ratio around 58,000 for an A item and 1,460 for a C. The
           fractile `short/(short+hold)` therefore exceeded 0.999 for all three
           criticalities and pinned to `service_level_cap` every time. "Service
           level from each item's own economics" was doing nothing at all, and the
           scenario slider would have drawn a flat line in front of the client.
           Both sides now sit on the same footing: cost of being short ONCE against
           cost of holding one unit for a YEAR. A = 0.994, B = 0.960, C = 0.800.
           `shortage_cost_per_unit_day` is kept for the backtest, where being short
           for a week should hurt more than for an hour, but it is explicitly not
           the fractile input.
Rejected: keeping per-day on both sides (arithmetically fine, operationally inert)
Reverses: CostModel as first written

---

## 2026-09-10 — Dead money defined once in config, not inside a test
Model: Opus 5
Type: decision
Reasoning: The 36% figure previously existed only inside a test's private formula,
           so nothing else could agree with it. `DeadMoneyRule` now holds the
           justified-quantity rule and the target band, and the generator tests,
           the console report and step-6 scoring all read it.
           Recorded here because the number we do NOT report matters as much: 89.6%
           of on-hand value has had no issue in 24 months. That is not dead money —
           insurance spares correctly sit still for years — and reporting it would
           inflate the prize 2.5x and collapse the first time a reliability engineer
           asked whether a spare transformer is waste.
Rejected: "value idle for 24 months" as the headline (bigger, indefensible)
Reverses: —

---

## 2026-09-10 — family_id removed from the source tables; material_group added
Model: Opus 5
Type: decision
Reasoning: A real SAP/PiLog extract has no column stating "these rows are the same
           part family", and leaving one in would let the duplicate matcher and the
           UOM check read the answer straight off the data. It moves to
           `truth_materials.true_family_id`.
           Partial disagreement with the review, and the reason is on the record: a
           real extract DOES carry a coarse material group (SAP MATKL), so removing
           every grouping signal would make the POC harder than reality in one
           direction while easier in another. `material_group` lumps several seed
           families into one bucket — a hint the engine can legitimately use, not a
           giveaway. A test asserts it has strictly fewer distinct values than the
           true family count.
Rejected: no grouping column at all (unrealistically hard); keeping family_id (cheating)
Reverses: MATERIALS as first written

---

## 2026-09-10 — Stocking is per POSITION, not per material
Model: Opus 5
Type: decision
Reasoning: Capability 5 (transfers) had literally no data: with one row per
           material there is no "one store holds 40 idle while another is about to
           buy five". `stock`, `truth_positions` and movements are now keyed on
           (material_id, storeroom_id), demand is split across stores per family,
           and ~17% of materials sit in more than one storeroom. Truth is split into
           `truth_materials` (what the item is) and `truth_positions` (what each
           store holds), because the two have different keys.
Rejected: a single-store model with synthetic transfers bolted on later
Reverses: STOCK and TRUTH as first written

---

## 2026-09-10 — Issues are recorded when SERVED, not when demanded
Model: Opus 5
Type: decision
Reasoning: The sim backorders when stock runs out, but the ledger logged the
           demand as an issue on the day it was raised. SAP cannot post an issue
           against stock that is not there — the maintenance job waits. The result
           was positions whose movements summed to -6 with nothing planted, so the
           ledger could never reconcile and LEDGER_MISMATCH would have fired on our
           own bookkeeping. `sim.walk` now returns a served-by-day matrix and the
           ledger is built from it.
Rejected: clamping openings upward to hide the gap (fudges the arithmetic)
Reverses: —

---

## 2026-09-10 — Every position opens with an ADJUST; stock is recomputed from the ledger
Model: Opus 5
Type: decision
Reasoning: `sum(movements.qty) == on_hand` held for 0% of positions, so the
           strongest data-quality check available — ledger reconciliation, the one
           an auditor recognises on sight — could not exist. Each position now opens
           with a day-0 ADJUST carrying its opening balance, injection adds opening
           rows for duplicate copies, and `stock` is recomputed from the ledger
           afterwards. Negative stock is planted LAST, because a negative balance IS
           a ledger disagreement and the recompute would otherwise erase it.
           Consequence worth noting: the reconciliation check is now asserted
           against the exact planted set, not a count threshold. The threshold
           version hid 52 positions that had gone negative on their own, each of
           which the engine was right to flag and the scoreboard counted as a false
           alarm — precision read 57% for being correct.
Rejected: tolerating a small number of unexplained mismatches
Reverses: —

---

## 2026-09-10 — Shutdowns actually consume parts
Model: Opus 5
Type: decision
Reasoning: Measured issue rate inside a smelter shutdown was 1.5/day against a
           2.0/day baseline — the outage had no effect on demand whatsoever, so the
           shutdown table was decoration and step 4's "a planned shutdown is known
           demand, not a surprise" had nothing behind it. Each family now carries a
           `shutdown_demand_mult` (cathode blocks 20x, refractory 10x, O-rings 1x)
           and outages add Poisson demand inside their window. Measured multiple is
           now 3.9x at toy and 3.5x at full, with `shutdown_intensity` giving
           headroom so an RNG reshuffle does not flip the check.
Rejected: leaving shutdowns as calendar entries with no demand effect
Reverses: —

---

## 2026-09-10 — Work orders carry advance notice, and group multiple parts
Model: Opus 5
Type: decision
Reasoning: 100% of work orders were dated the same day as the issue and averaged
           1.01 parts. A planned job raised the day it consumes parts gives a
           forecaster nothing to know in advance, which is precisely what step 4
           needs. WORK_ORDERS now carries `created_date` and `planned_date`; planned
           jobs are raised 14-60 days ahead, shutdown jobs 90-240. Measured: 100%
           raised in advance, median 37 days notice, 2.3 issues per job.
           ponytail, recorded honestly: issues are grouped by (equipment, month) as
           a proxy for one maintenance visit. Demand is sampled per material
           independently, so ANY grouping imposed afterwards is synthetic. The
           honest fix is to invert the model — sample work orders, then draw parts
           from the asset's BOM — which is a larger change than this slice
           justifies. Marked in the code.
Rejected: WO-per-issue (no advance signal, nothing for step 4 to learn)
Reverses: —

---

## 2026-09-10 — Truth profile derived from realised behaviour, not the family label
Model: Opus 5
Type: decision
Reasoning: 43% of items labelled `consumable` had two or fewer issues in three
           years, and one carried `true_demand_interval_days = 1409` — the truth
           label contradicted the truth parameters printed beside it, so any
           classifier scored against it would have been graded on noise. The label
           now comes from the item's realised interval via `profile_cuts_days`; the
           family's label is kept as `seed_profile` for debugging only.
Rejected: keeping the family label as truth
Reverses: —

---

## 2026-09-10 — Typed equipment, per-family manufacturers and size tokens
Model: Opus 5
Type: decision
Reasoning: The master data failed the ten-second test: "OIL, GEAR LUBRICATING,
           188MM" by Parker, "BATTERY, UPS, 80MM" by Flexitallic, hex bolts by Rio
           Tinto Alcan, and a bolt, an oil, a battery, a bearing and a seal kit all
           fitted to EQ-00001. A demo dataset a maintenance engineer laughs at
           destroys every number computed from it.
           Now: `seeds/equipment_types.csv` gives named, typed assets ("Pot 005,
           Line 2", "Slurry pump SL001"); families declare their own manufacturer
           pool and token type, so a bearing renders as 6205 and an oil as ISO VG
           220; and materials attach only to assets of a matching type. Every asset
           type is guaranteed at least one instance, which cut materials landing on
           a generic asset from 40% to 7%.
Rejected: a single global manufacturer list and one "{n}MM" token for everything
Reverses: —

---

## 2026-09-10 — Commissioning packages buy ONE of an expensive spare
Model: Opus 5
Type: decision
Reasoning: The package was 1-4 units regardless of price, which put five SAR 2m
           spare transformers on the shelf and made them a third of all dead money
           on their own. Above `single_unit_above_sar` the package is one unit. A
           plant buys one spare transformer.
Rejected: flat 1-4 units (dead money became an artefact of the generator)
Reverses: the units range as first written

---

## 2026-09-10 — Scoring identity is per defect type
Model: Opus 5
Type: decision
Reasoning: The first scorer keyed every finding on (type, material, storeroom).
           ISSUE_WITHOUT_WORK_ORDER could therefore never score — the planted key
           carried a movement_id and the finding key hardcoded "" — so every correct
           orphan finding counted as a miss AND a false alarm. DUPLICATE_MATERIAL
           was an ordered pair, so a correct finding naming the two masters the
           other way round also failed. FINDINGS gains `movement_id` and
           `related_material_id`; duplicates match as an unordered frozenset;
           counts use Counter so one material can carry several planted defects.
Rejected: one key shape for all types (silently zeroes two of seven checks)
Reverses: —

---

## 2026-09-10 — The engine declares which checks ran
Model: Opus 5
Type: decision
Reasoning: Inferring "implemented" from the finding types present means a check
           that ran and found nothing is indistinguishable from one nobody has
           written — a 100% miss reported as work not started, which is the most
           flattering possible failure and the hardest to notice. The engine writes
           `implemented_checks.json` listing scored and informational checks, and
           scoring refuses to run without it.
Rejected: inference from findings (hides total failure as absence)
Reverses: —

---

## 2026-09-10 — Informational findings are counted, not penalised
Model: Opus 5
Type: decision
Reasoning: LEDGER_MISMATCH and its kind have no planted counterpart, and counting
           them as false alarms penalises the engine for finding real problems —
           precision read 50% while every finding was correct. They are reported
           with counts and excluded from precision. The counts stay prominent so a
           check that starts firing on thousands of rows is still visible.
Rejected: counting them as false alarms; hiding them entirely
Reverses: —

---

## 2026-09-10 — sim walks all items at once
Model: Opus 5
Type: decision
Reasoning: The per-item Python loop would have cost hours on the full preset once
           the twenty-point service-level sweep multiplied it. The loop is now over
           days with numpy across items, `on_order` is a running array instead of a
           slice-sum per review (the O(n^2)), and lead times are drawn per order
           from a lognormal — lead-time variance is half of what safety stock exists
           for, and with a fixed lead time both policies look better than they are.
           Combined with a vectorised work-order builder, which was 86% of the
           generation run on its own, full-preset build+run+score went from 2m04s to
           13.6s.
Rejected: per-item loop with multiprocessing (same asymptotics, more moving parts)
Reverses: —

---

## 2026-09-10 — Process chemicals marked out of scope
Model: Opus 5
Type: decision
Reasoning: Caustic soda, lime, aluminium fluoride and cryolite are process raw
           materials, not MRO spares. They stay in the seed file with `in_scope=0`
           so the engine can be shown excluding them — a Ma'aden planner will ask
           where the caustic went — but they are not stocked as spares and do not
           enter the dead-money or reorder-point numbers, which would otherwise mix
           two different working-capital conversations.
Rejected: dropping them from the seed entirely (loses the chance to show exclusion)
Reverses: —

---

## 2026-09-10 — git_sha warns rather than failing the build
Model: Opus 5
Type: decision
Reasoning: The review offered failing the build or warning loudly. Warning, because
           the pipeline has to run from a temp directory (the CLI smoke test does
           exactly this) and from CI checkouts without history, and refusing to
           build there costs more than the missing SHA does. `config_hash` plus
           `seed` still pin the dataset exactly, so a run without a SHA is still
           reproducible — just not traceable to code, which is what the warning says.
Rejected: hard failure (breaks the test suite and any zip-and-run)
Reverses: —

---

## 2026-09-10 — Work-order grouping stays synthetic; WO-first sampling deferred
Model: Opus 5
Type: decision
Reasoning: Issues are grouped into jobs by (equipment, month) after the fact. Demand
           is sampled per material independently, so any grouping imposed afterwards
           is invented — the number of parts on a job is a property of our grouping
           rule, not of the plant.
           This surfaced when the issues-per-WO target was 2.0 and the natural
           grouping produced 1.8. The fix applied at the time was to widen job sizes
           to 2-8 parts, which cleared the target by tuning the plant to fit the
           metric — exactly backwards. Job sizes are now back to their natural
           (1,6)/(1,3) and the target is 1.5, which the grouping meets honestly.
           DEFERRED CHANGE — invert the model: sample work orders first (an asset
           has a maintenance event), then draw the parts consumed from that asset's
           BOM. Parts-per-job then falls out of the BOM and the job type rather than
           from a bucketing rule, and issues-per-WO becomes a measurement instead of
           a knob. It also gives step 4 a much better signal: a planned job's parts
           would be predictable from the asset and the job type, which is what
           "maintenance plans drive demand" actually means.
           Not done now because it inverts the generator's core loop and the slice
           needs closing first. Marked with a `ponytail:` comment at
           generator/demand.py:build_work_orders.
Rejected: widening job sizes to hit the target (tunes the plant to fit the metric)
Reverses: the (2,8)/(1,4) sizes introduced the same day

---

## 2026-09-10 — material_group kept, with a cardinality test
Model: Opus 5
Type: decision
Reasoning: Reviewer accepted the partial disagreement on removing every grouping
           column. `family_id` stays out of the source tables, but `material_group`
           (a coarse SAP MATKL analogue) remains, because a real extract has one and
           removing all grouping signal would make the POC unrealistically hard in
           one direction while the missing column makes it unrealistically clean in
           another. `test_family_id_is_not_in_the_source_tables` asserts it has
           strictly fewer distinct values than the true family count, so it stays a
           hint the engine may legitimately use rather than the answer.
Rejected: no grouping column at all
Reverses: —

---

## 2026-09-10 — POC scope fixed to three claims
Model: Opus 5
Type: approval
Reasoning: Scope agreed with the reviewer and written into IMPLEMENTATION-PLAN.md,
           which is now the authority on what gets built. The POC proves exactly
           three things: that data problems can be found and measured against the
           answer key; that stock levels can beat the plant's own min/max, measured
           by backtest; and that a planner can ask a question in English and get a
           checkable answer. Anything not serving one of those is out.
           Explicitly excluded: LightGBM, embedding matching, Arabic, login, SAP
           connection, purchase orders, and any screen beyond the dashboard and the
           item view. Transfers, the scenario slider and the work queue happen only
           if everything above is green.
Rejected: building all seven capabilities to equal depth (dilutes the two that sell it)
Reverses: —

---

## 2026-09-10 — rapidfuzz and scikit-learn added for the matcher
Model: Opus 5
Type: decision
Reasoning: Required by the duplicate matcher, and both were named in the original
           approach: scikit-learn for TF-IDF character n-grams and nearest-neighbour
           blocking, rapidfuzz for the string scorers. Blocking is not optional —
           20,000 masters is 200 million pairs, and the TF-IDF step cuts that to
           80,000 candidates while still containing 100% of the true pairs.
           Both are inspectable and neither downloads a model at runtime, which is
           the property that kept sentence-transformers out.
Rejected: hand-rolled n-gram similarity (slower, and no better)
Reverses: —

---

## 2026-09-10 — Variants carry two characteristics, not one dimension
Model: Opus 5
Type: reversal
Reasoning: Duplicate detection scored 0% precision, and the cause was the data, not
           the matcher. One dimension drawn from a small vocabulary cannot keep a
           family apart: 300 valves drawn from 16 DN sizes repeat themselves
           nineteen times over. Measured on the full preset, 85% of materials shared
           a description with another row and there were 82,370 accidental identical
           pairs against 140 planted ones.
           On that data the task was not merely hard, it was meaningless — a matcher
           flagging identical descriptions was right, and the scoreboard called it
           wrong. Descriptions now carry a dimension plus a characteristic (material,
           rating, class), generated per family as unique combinations, so an
           identical description means what it should mean: somebody entered the
           part twice. A test asserts zero repeats outside the planted copies.
Rejected: loosening the matcher to tolerate the collisions (fitting the model to a
          broken fixture)
Reverses: the single-token descriptions in generator/build.py

---

## 2026-09-10 — Part numbers are near-binary evidence
Model: Opus 5
Type: decision
Reasoning: Scoring MPN similarity as a character ratio gave two unrelated parts from
           the same maker 0.67, because they share a prefix and most of their
           digits. That propped up every sibling pair in the catalogue and was the
           single largest source of false matches.
           Two different part numbers mean two different parts; there is no "partly
           the same part". Only a near-identical string is treated as a possible
           mis-key. SKF1001 against SKF1002 scores zero — sequential catalogue
           numbers are different products, not a typo.
           Blank stays NaN: absence of a part number is absence of evidence, which
           matters because losing the MPN is exactly what a re-keyed duplicate does.
Rejected: a graded string ratio (mathematically smooth, semantically wrong)
Reverses: —

---

## 2026-09-10 — Catalogue frequency separates a typo from a variant
Model: Opus 5
Type: decision
Reasoning: "DN65" against "KN65" and "GRADE A" against "GRADE B" are both one
           character apart. The first is a mis-key, the second is a different
           product, and no string metric can tell them apart.
           What can is how often the token appears in the catalogue: KN65 occurs
           once in twenty thousand rows, GRADE A occurs thousands of times. A rare
           token that closely resembles a token on the other side is paired off and
           stops counting against the match; a common one counts in full. This is
           standard master-data practice — a value outside the known value set is a
           data error — and it lifted duplicate recall from 82% to 96% without
           costing precision.
           Both halves of a matched pair are consumed. Excusing only the rare half
           left the union inflated and dragged genuine pairs to a half score.
Rejected: fuzzy string matching on the whole description (cannot distinguish the two)
Reverses: —

---

## 2026-09-10 — UOM mismatch: what it catches, and what it cannot
Model: Opus 5
Type: decision
Reasoning: Detected by rarity within a material group that otherwise speaks one
           unit, excluding blanks (which are rarer than anything and are already
           reported as BLANK_UOM). 86% recall at 100% precision on the full preset.
           The limit is measured, not assumed: this catches an item swapped into a
           RARE unit and cannot catch one swapped into the group's dominant unit,
           which looks exactly like its peers. All eleven misses are that shape.
           Price was tested as a second signal — the idea being that a unit changed
           without a price change leaves the price fitting the old unit's peers —
           and abandoned: only 8 of 80 planted cases had enough same-group same-unit
           peers for the comparison to have any power, and the measured separation
           was zero.
Rejected: a price-consistency scorer (no measurable signal in this data)
Reverses: —

---

## 2026-09-10 — Duplicate threshold selected on our own data
Model: Opus 5
Type: decision
Reasoning: 0.77, the middle of the band that clears both targets on the full preset
           (0.76 and 0.78 both pass), and unchanged on toy, which is an independent
           draw. Full: 96% recall at 88% precision. Toy: 3 of 3, no false alarms.
           Recorded because it matters how this number was chosen: it was selected
           against the same answer key it is scored on. That is legitimate model
           selection but it is not a held-out result, and a real deployment must
           re-tune it on a labelled sample of the client's own master. The number is
           a starting point, not a constant of nature. The comment at
           engine/quality.py:DUPLICATE_THRESHOLD says so.
Rejected: quoting it as a validated constant
Reverses: —

---

## 2026-09-10 — Generator must not plant two defects on the same field
Model: Opus 5
Type: decision
Reasoning: BLANK_UOM scored 59 of 60 and the missing one was not an engine failure:
           the generator blanked a unit and then applied UOM_MISMATCH to the same
           row, overwriting it. The answer key claimed a blank that was not there,
           so the engine was marked wrong for being right.
           UOM_MISMATCH now draws only from rows that still have a unit. This is the
           worst class of scoring bug, because it presents as an engine failure and
           sends you looking in the wrong module.
Rejected: tolerating a one-row discrepancy
Reverses: —

---

## 2026-09-10 — Dead-value band is asserted at full scale only
Model: Opus 5
Type: decision
Reasoning: Dead value is a VALUE-weighted share, so at 300 materials a handful of
           expensive rows decide it: measured 15% on toy against 29% on full from
           the same generator, and it moves several points on any reshuffle of the
           random stream. Sweeping a parameter through it gave 26%, 16%, 27% for
           three neighbouring values, which is noise, not response.
           The industry band (20-40%) is therefore asserted where it means
           something — the full preset — and toy gets a wide sanity range so a
           genuinely broken generator still fails there. The report says which band
           it used.
Rejected: tuning the generator until toy landed in the industry band (fitting to noise)
Reverses: the single band in DeadMoneyRule

---

## 2026-09-10 — material_group was kept against an explicit instruction
Model: Opus 5
Type: approval
Reasoning: The review asked for `family_id` to be removed from the source tables so
           the matcher and the UOM check could not read the answer off the data. I
           removed it, and then added `material_group` — a coarser grouping — which
           both of those checks now use. That was an override of an explicit
           instruction, and the previous report framed it as a disagreement without
           saying plainly that the instruction had not been followed. It should have.
           Recorded now with the reviewer's agreement.

           Why it is legitimate: SAP MATKL is a real field on every material master,
           and PiLog's taxonomy carries a class node above it. An extract with no
           grouping column at all does not exist, so removing every one would make
           the POC unrealistically hard in one direction while the missing column
           made the data unrealistically clean in another. `material_group` buckets
           several seed families together and
           `test_family_id_is_not_in_the_source_tables` asserts it has strictly fewer
           distinct values than the true family count — it is a hint, not the answer.

           What will be different on real data, and it matters: our groups are clean
           because we generate them. A real MATKL is maintained by hand over decades,
           so it will be noisier — miscoded rows, groups that mean different things
           in different plants, a long tail of catch-all codes. Both consumers must
           degrade rather than break:
             * UOM_MISMATCH already requires the group to be strongly dominated by
               one unit before it says anything, so a mixed or miscoded group simply
               produces no finding.
             * The matcher uses the group only in the low-weight `attributes` scorer,
               never for blocking, so a wrong group costs a little confidence and
               cannot hide a duplicate.
           Both of those should be re-measured on the pilot extract rather than
           assumed to hold.
Rejected: removing every grouping column (no real extract looks like that)
Reverses: partially reverses the 2026-09-10 entry "family_id removed from source"

---

## 2026-09-10 - TSB chosen for both sparse classes, on measurement
Model: Opus 5
Type: decision
Reasoning: All four Croston-family combinations were run on the full preset and
           scored on the evaluation year. On the intermittent class, which is 83% of
           all positions: Croston 1.033, SBA 1.012, TSB 0.871. On lumpy: SBA 0.848,
           TSB 0.837.
           TSB wins both, and by a wide margin where it matters most. The reason is
           structural rather than lucky: TSB updates the probability that demand
           occurs at all in EVERY period, including the months where nothing
           happened, whereas Croston and SBA only update when something moves. On a
           series that is mostly zeros, the zeros are most of the information.
Rejected: SBA on intermittent (the obvious default, and measurably worse here)
Reverses: -

---

## 2026-09-10 - We lose to the zero baseline on sparse demand, and say so
Model: Opus 5
Type: decision
Reasoning: On the full preset the forecast beats both baselines on the two dense
           classes (smooth 0.86 against 1.11 and 1.48; erratic 0.84 against 1.19 and
           1.00) and beats the naive baseline but NOT the zero baseline on the two
           sparse ones (intermittent 0.87 against 0.98 and 0.71; lumpy 0.84 against
           1.04 and 0.76).
           This is reported prominently rather than buried, because it is the
           expected result and hiding it would be the kind of thing that destroys
           credibility the moment a statistician in the room notices. When a part
           moves four times in two years, always answering zero is wrong only four
           times and produces the smallest average error of any possible answer.
           It is also a useless answer. A forecast of zero sets a reorder level of
           zero, which guarantees a stockout on every critical spare in the plant.
           Average forecast error is the wrong scoreboard for this problem, which is
           exactly why the decisive test is the step-5 backtest measured in days
           without a part and capital tied up.
Rejected: quoting only the naive comparison, which we win everywhere
Reverses: -

---

## 2026-09-10 - expected_life_years added to the master, deliberately noisy
Model: Opus 5
Type: decision
Reasoning: A part that has never once been issued has no history to forecast from,
           and forecasting zero on a spare whose absence stops the plant is the worst
           available answer. The failure-rate model needs an expected service life.
           `mtbf_years` lives in the answer key, so the engine cannot use it. A
           planning attribute for expected service life is a real field - SAP and
           PiLog both carry one - so it was added to the material master.
           Crucially it is generated as a PLANNER'S ESTIMATE, not the truth: the real
           interval multiplied by a lognormal error, landing between about 0.63 and
           1.57 times the true value at the tenth and ninetieth percentiles. Handing
           the engine the exact figure would have leaked the answer key through a
           source column, which is the same failure as reading the answer key
           directly but considerably harder to notice.
Rejected: deriving a rate from the equipment population alone (weaker, no more honest)
Reverses: -

---

## 2026-09-10 - statsforecast added
Model: Opus 5
Type: decision
Reasoning: Provides Croston, SBA and TSB as tested implementations. Writing three
           intermittent-demand methods by hand, and then having their behaviour
           questioned by a reliability engineer, is the wrong use of the time; the
           library is the reference implementation the literature is written against.
           LightGBM stays out, per the agreed scope, and has been removed from the
           dependency list so it cannot creep back in.
Rejected: hand-written Croston variants
Reverses: -

---

## 2026-09-10 - Shutdown multiple joins dead value as a full-scale-only target
Model: Opus 5
Type: decision
Reasoning: Same reasoning as the dead-value band, and the same evidence: with three
           shutdowns and 300 parts the measured multiple is a small-sample statistic.
           It reads 2.1x on toy and 3.5x on full from the same generator, and moves
           on any reshuffle of the random stream.
           The 3x target is asserted at full scale. Toy asserts only that an outage
           has a visible effect at all (1.5x), so a genuinely broken overlay still
           fails there. Tuning the generator until toy cleared 3x would be fitting to
           noise, which is the mistake the dead-value entry already records.
Rejected: one target for both presets
Reverses: -
