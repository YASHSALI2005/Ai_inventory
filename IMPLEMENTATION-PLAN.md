# How We Build It — Implementation Plan

Ma'aden MRO Intelligence POC · **Phase 1 approved**
Written plainly, for the person building it. Tick steps off as they land.

---

## What we are building — four things

| # | Thing | What it is |
|---|---|---|
| 1 | **The data maker** | A program that creates fake SAP + PiLog + maintenance data, with problems hidden inside and a sealed answer key |
| 2 | **The brain** | Four engines: clean the data → sort & predict → set stock levels → find dead money and transfers |
| 3 | **The API** | A thin layer that serves the brain's answers to the screens |
| 4 | **The screens** | Dashboard · planner work queue · scenario slider · chat |

Nothing else. No login system, no SAP connection, no purchase orders.

---

## Folder layout

```
maaden-mro-poc/
├── data/                  generated files live here (not committed)
│   ├── materials.parquet      the PiLog dictionary
│   ├── stock.parquet          the SAP stock book
│   ├── movements.parquet      3 years of issues & receipts
│   ├── equipment.parquet      the maintenance book
│   └── answer_key.json        what we broke on purpose  ← engine NEVER reads this
├── generator/             step 1
├── engine/                steps 2–6  (pure logic, no database, no web)
├── api/                   step 7
├── ui/                    step 7
├── scoring/               grades the engine against the answer key
└── docs/
```

**One rule that matters:** `engine/` never imports from `generator/`, and never opens
`answer_key.json`. If it could see the answers, the score would be meaningless — and we would
not notice until a client asked how we measured it.

---

## The eight steps

Each step has: what we build, what exists at the end, and how we know it works.

---

### Step 1 — The data maker

**Build:** a program that writes the five files above.

- 5 storerooms · ~400 machines · ~20,000 parts · 3 years of daily movements
- Each part is linked to the machine it belongs to
- Day-by-day simulation: did something break today? → part issued → stock drops → reorder
  raised → delivery arrives weeks later
- Four kinds of usage behaviour: everyday, occasional, rare-and-lumpy, almost-never
- Planned shutdowns create demand spikes on known dates
- **Then break it on purpose** and write every break into `answer_key.json`:
  duplicates · obsolete stock · negative balances · blank part numbers · wrong units ·
  overstocked items · critical items below reorder point

**Done when:** the five files exist and you can open them and they look like a real plant.

**Check:** row counts match targets; the usage mix looks like real MRO (most parts rarely
moving); the answer key lists every planted defect with its ID.

> This step is the foundation. If the data is fake-looking, every demo after it is unconvincing.
> Worth spending real time here.

---

### Step 2 — Clean the data *(capability 4)*

**Build:** the checks — negative stock, blank mandatory fields, wrong units, impossible lead
times, usage with no work order, plus the duplicate-part matcher.

**Done when:** it outputs a list of problems, each with an ID and a reason.

**Check:** run `scoring/` against the answer key → **"found X of Y planted, Z false alarms."**
**This is our first real number.**

---

### Step 3 — Sort the parts *(the classifier)*

**Build:** for each part, measure how often it moves and how much the quantity jumps around,
then label it: everyday / jumpy / occasional / rare-and-lumpy.

**Done when:** every part has a label.

**Check:** the split should look like real MRO — most parts in the occasional and lumpy
groups, few in everyday. If it comes out mostly "everyday", the generator in step 1 is wrong,
not the classifier.

---

### Step 4 — Predict *(capability 1)*

**Build:** a different method per label — Croston/SBA/TSB for the rare movers, LightGBM for the
fast movers, failure-rate model for the almost-nevers. Add planned shutdowns on top as known
demand.

**Done when:** every part has a 6-month forecast.

**Check:** accuracy (MASE) reported **per group**, compared against a dumb baseline
("next month = last month"). We must beat the baseline, and we report honestly where we don't.

---

### Step 5 — Set the levels *(capability 3)*

**Build:** reorder point + safety stock for every part in every store. Empirical quantiles for
the lumpy ones, service level from each item's own economics, criticality override so a
critical spare is always stocked at least 1.

**Done when:** every part-store pair has two numbers and a plain-English reason.

**Check:** replay 3 years of history with our levels vs a plain min/max baseline. Count
stockout days, units short, money tied up. **This is our second real number.**

---

### Step 6 — Dead money and transfers *(capabilities 2 & 5)*

**Build:**
- Dead money — compare what's on hand against what step 5 says is needed; flag never-used,
  obsolete (machine gone), duplicated, overstocked. Value it in SAR.
- Transfers — who has spare, who needs it, cost tiered by distance (same site vs 600 km).

**Done when:** two ranked lists, both in SAR.

**Check:** score the dead-money list against the answer key.

---

### Step 7 — API and screens

**Build:** FastAPI serving the engine's output, and four screens:

| Screen | Shows |
|---|---|
| **Dashboard** | Money at risk, dead money, service level — by store |
| **Work queue** | What to do today, ranked in SAR, not by colour code |
| **Item view** | One part: usage chart, forecast, recommended levels, the reasoning |
| **Scenarios** | Service level slider → cash freed vs risk taken *(capability 6)* |

**Done when:** it opens in a browser and you can click through all four.

---

### Step 8 — Chat *(capability 7)*

**Build:** Claude with a **fixed list of tools** — `get_stockouts()`, `get_dead_money()`,
`get_item()`, `get_transfers()`. The model picks a tool, the engine computes, the model reads
the answer back with the numbers and the item list shown underneath.

**No writing SQL. No doing maths. Narration only.**

**Done when:** you can type "which critical spares at the smelter are below reorder point"
and get a correct, checkable answer.

---

### Step 9 — The demo

**Build:** a 10-minute click-through that tells the same story as the pitch deck —
the 2am bearing, the dead filters, then the same day with the system running. Plus a
one-page results sheet with the two scores from steps 2 and 5.

---

## Tools we'll use

| For | Choice |
|---|---|
| Everything backend | Python 3.12 |
| Data files | Parquet + DuckDB — **no database server to install** |
| Forecasting | `statsforecast` (Croston/SBA/TSB), LightGBM |
| Duplicate matching | RapidFuzz + scikit-learn TF-IDF |
| API | FastAPI |
| Screens | React + Vite + Tailwind |
| Chat | Claude, tool use |

**Change from the client build plan:** that document proposed PostgreSQL. For a POC on a few
million rows, a database server is setup cost with no benefit — Parquet files plus DuckDB do
the same job with nothing to install. If the pilot needs a real server later, that swaps behind
the adapter layer, which is exactly what the adapter layer is for.

---

## Order of work, and why

```
1 data  →  2 clean  →  3 sort  →  4 predict  →  5 levels  →  6 dead money  →  7 screens  →  8 chat
```

Every step needs the one before it:
- can't measure anything without **1**
- can't trust anything without **2**
- can't predict without knowing which method to use → **3**
- can't set levels without a prediction → **4**
- can't call stock "excess" until you know what "enough" is → **5**
- nothing to show until the numbers exist → **7**
- chat narrates what the engine computed → **8** last

---

## What "done" looks like

At the end we can say, with numbers rather than adjectives:

- *"We hid 100 problems. It found 94. It raised 6 false alarms."*
- *"Against a normal min/max policy, over the same 3 years: X% fewer stockout days, SAR Y less
  capital tied up."*
- *"Here is SAR Z of dead stock, listed item by item."*
- And a working screen where you can ask it a question in English.

---

## Ground rules while building

- **The engine never sees the answer key.** Non-negotiable.
- **Score after every engine step** — don't build all four and measure at the end.
- **Every recommendation carries a plain-English reason.** A number a planner can't question
  is a number they won't act on.
- **The chat never calculates.**
- **No new library without a reason** — the maths must stay readable to a domain expert.

---

## Three things to confirm before I start

1. **Backend Python + React frontend** — same shape as the last project, or something else?
2. **Parquet + DuckDB instead of PostgreSQL** for the POC — agreed?
3. **How real should the demo data feel?** Generic industrial parts, or properly
   aluminium-specific (anode assemblies, cathode blocks, work rolls, digester spares)?
   The second is more convincing to Ma'aden engineers and takes longer to build.
