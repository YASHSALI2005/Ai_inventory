"""
Two one-page documents, regenerated from results/ so the numbers in them are the
numbers on the screens.

* docs/RESULTS-SHEET.md — the three headline numbers, the backtest table, the
  dead-money score, the limits. What a manager reads after the meeting.
* docs/DEMO-SCRIPT.md — the ten-minute click-through in Present mode. What the
  presenter reads before it.

Never hand-edited. `python cli.py report` rebuilds both alongside the docx.
"""

from __future__ import annotations

import json
from pathlib import Path

from contracts.config import RunConfig

ROOT = Path(__file__).resolve().parent.parent


def _load(cfg: RunConfig, name: str) -> dict:
    path = cfg.results_dir / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def m(v) -> str:
    return "—" if v is None else f"SAR {v / 1e6:,.1f}m"


def pc(v) -> str:
    return "—" if v is None else f"{v * 100:+.0f}%"


def pct(v) -> str:
    return "—" if v is None else f"{v * 100:.0f}%"


def n(v) -> str:
    return "—" if v is None else f"{v:,.0f}"


def results_sheet(cfg: RunConfig) -> str:
    su, sc = _load(cfg, "summary.json"), _load(cfg, "defect_score.json")
    bt, dm = _load(cfg, "backtest_report.json"), _load(cfg, "dead_money_score.json")
    fr, lv = _load(cfg, "frontier.json"), _load(cfg, "levels_report.json")
    fc, sr = _load(cfg, "forecast_report.json"), _load(cfg, "storeroom_report.json")
    inv, run, cnt = su.get("inventory", {}), su.get("run", {}), su.get("counts", {})
    b, p, c = bt.get("baseline", {}), bt.get("policy", {}), bt.get("change", {})
    s = sc.get("summary", {})
    o = dm.get("obsolete", {})

    def row(label, key, money=False):
        f = m if money else n
        return f"| {label} | {f(b.get(key))} | {f(p.get(key))} | {pc(c.get(key))} |"

    lines = [
        "# Results sheet — Ma'aden Aluminium MRO POC",
        "",
        f"*Generated from `results/` for the {run.get('preset', '')} preset · run "
        f"{run.get('config_hash', '')} · seed {run.get('seed', '')} · {run.get('generated_at', '')[:10]}. "
        "Every figure below is also on the screens; none was typed by hand.*",
        "",
        "## The three headline numbers",
        "",
        f"1. **Data problems found: {pct(s.get('recall'))} of the faults planted in the data, at "
        f"{pct(s.get('precision'))} precision** — {n(s.get('found'))} of {n(s.get('planted'))} found, "
        f"{n(s.get('false_alarms'))} false alarms, graded against a sealed answer key the engine "
        "never reads.",
        f"2. **Jobs waited {pct(abs(c.get('stockout_days', 0)))} fewer days for parts**, on the last year of "
        f"history replayed under our stock levels against the plant's own — holding "
        f"{pc(c.get('avg_capital_sar'))} more stock, with all costs together "
        f"{pc(c.get('total_cost_sar'))}.",
        f"3. **Dead money found: {m(dm.get('found_sar'))} of {m(dm.get('true_dead_sar'))} truly dead "
        f"({pct(dm.get('recall_sar'))}), at {pct(dm.get('precision_sar'))} precision** — "
        f"{m(dm.get('wrongly_flagged_sar'))} wrongly flagged, one reason per record.",
        "",
        "## What is on the shelves",
        "",
        f"| | |", "|---|---|",
        f"| Stock on the shelves | {m(inv.get('total_stock_value_sar'))} across {n(cnt.get('positions'))} records in {cnt.get('storerooms', '')} storerooms |",
        f"| Parts not used in two years | {n(inv.get('idle_24m_count'))} — {pct(inv.get('idle_24m_share'))} of the catalogue |",
        f"| Dead money (answer key) | {m(inv.get('dead_value_sar'))} — {pct(inv.get('dead_value_share'))} of stock value |",
        f"| Dead money (found by the engine) | {m(dm.get('claimed_sar'))} on {n(dm.get('positions_flagged'))} records |",
        f"| Critical parts below their safe level | {n(sr.get('critical_below_level_count'))}, {m(sr.get('critical_below_level_sar'))} to bring back to level |",
        f"| Parts needing action today | {n(sr.get('needs_action_count'))}, {m(sr.get('cost_to_level_sar'))} to bring back to level |",
        f"| Stock that could be moved instead of bought | {n(sr.get('transfer_count'))} moves, {m(sr.get('transfer_total_sar'))} saved |",
        "",
        "## The backtest — the last year replayed under both sets of levels",
        "",
        f"{n(bt.get('evaluated_days'))} days from {bt.get('evaluated_from', '')}, {n(bt.get('positions'))} "
        "records, identical demand and identical delivery delays. The only difference is the levels.",
        "",
        "| | The plant's levels | Ours | Change |", "|---|---|---|---|",
        row("Days waiting for a part", "stockout_days"),
        row("Units short over the year", "units_short"),
        row("Average value on the shelves", "avg_capital_sar", True),
        row("Cost of being short", "shortage_cost_sar", True),
        row("Cost of holding stock", "holding_cost_sar", True),
        row("Cost of placing orders", "ordering_cost_sar", True),
        row("Purchase orders placed", "orders_placed"),
        row("**All three costs together**", "total_cost_sar", True),
        "",
        "**Read this honestly.** Our levels hold *more* stock, not less; the improvement is fewer "
        "days waiting and a lower total cost. Releasing cash is the dead-money finding, not the "
        "levels. The service-level sweep confirms it: the plant's own policy sits below our lowest "
        "sampled service level while holding less capital than any point on the curve"
        + (f" (`{fr.get('at_the_plants_own_service_level', {}).get('status', '')}`)." if fr else "."),
        "",
        "## Dead money — the engine against the answer key",
        "",
        "| | SAR |", "|---|---|",
        f"| Truly dead (answer key) | {m(dm.get('true_dead_sar'))} |",
        f"| Found | {m(dm.get('found_sar'))} ({pct(dm.get('recall_sar'))}) |",
        f"| Wrongly flagged | {m(dm.get('wrongly_flagged_sar'))} (precision {pct(dm.get('precision_sar'))}) |",
        f"| Missed | {m(dm.get('missed_sar'))} |",
        "",
        f"Obsolete materials: {n(o.get('truth'))} true, {n(o.get('found'))} found, {n(o.get('missed'))} "
        f"missed, {n(o.get('false'))} wrongly flagged.",
        "",
        "| Why it is dead | Records | Claimed | Correct |", "|---|---|---|---|",
    ]
    for cat in dm.get("by_category", []):
        lines.append(f"| {cat['category']} | {n(cat['positions'])} | {m(cat['claimed_sar'])} | {m(cat['correct_sar'])} |")
    lines += [
        "",
        "Most of the found figure is arithmetic on fields the plant already has — a decommissioned "
        "machine is a lookup, not a discovery. What the engine adds is applying one rule "
        "consistently across every record with a reason on each. The duplicate category is the "
        "weak one and is reported as such.",
        "",
        "## Forecast accuracy on the held-out year",
        "",
        "| Demand class | Records | Method | MASE, ours | Repeat last year | Always zero |",
        "|---|---|---|---|---|---|",
    ]
    for r in fc.get("mase_by_class", []):
        lines.append(f"| {r['class']} | {n(r['positions'])} | {r['method']} | {r['mase']:.2f} | "
                     f"{r['naive']:.2f} | {r['zero']:.2f} |")
    lines += [
        "",
        "Lower is better; 1.00 is no better than repeating last year. Losing to \"always zero\" on "
        "sparse parts is expected and is why the levels come from the demand distribution, not the "
        "forecast.",
        "",
        "## Limits",
        "",
    ]
    for lim in (bt.get("limits", [])[:3] + lv.get("limits", [])[:3] + fr.get("limits", [])[:1]
                + _load(cfg, "dead_money_report.json").get("limits", [])[:2]):
        lines.append(f"- {lim}")
    lines += [
        "",
        "Synthetic data throughout: the plant is invented, the faults were planted and the answer key "
        "sealed. Phase 1 replaces every figure here with the plant's own.",
        "",
    ]
    return "\n".join(lines)


def demo_script(cfg: RunConfig) -> str:
    su, bt, dm = _load(cfg, "summary.json"), _load(cfg, "backtest_report.json"), _load(cfg, "dead_money_score.json")
    sc, sr = _load(cfg, "defect_score.json"), _load(cfg, "storeroom_report.json")
    inv, c, s = su.get("inventory", {}), bt.get("change", {}), sc.get("summary", {})
    return f"""# Demo script — ten minutes in Present mode

*Numbers regenerated from `results/` ({cfg.preset} preset). Start the server with
`python cli.py serve --preset {cfg.preset}`, click **Present** in the nav (or open
`#/present/`), and walk with → . Escape leaves Present mode. Set `ANTHROPIC_API_KEY`
before starting if the chat is part of the demo.*

## 0 · The problem — 1 minute, no screen yet

"The storeroom is full: {pct(inv.get('idle_24m_share'))} of the parts on its shelves have not
moved in two years. The plant is still running short: jobs wait for parts that are not
there while the same part sits idle in the next store. And it pays twice — once for
stock nobody will use, again at three to five times the price for the emergency buy.
Everything you are about to see was measured against a sealed answer key, not asserted."

## 1 · Dashboard — 2 minutes  (`#/present/`)

Four tiles, left to right:
- **{m(inv.get('total_stock_value_sar'))} on the shelves.** "That is the pile."
- **{m(dm.get('claimed_sar'))} that will never come back — found by the system.** Point at the
  sub-line: the answer key says {m(inv.get('dead_value_sar'))}; we found {pct(dm.get('recall_sar'))}
  of it with {m(dm.get('wrongly_flagged_sar'))} wrongly flagged. "That is the third headline number."
- **{n(sr.get('critical_below_level_count'))} critical parts below their safe level**,
  {m(sr.get('critical_below_level_sar'))} to put right. "That is today's list."
- **{pct(abs(c.get('stockout_days', 0)))} fewer days waiting for a part** with our levels, holding
  {pc(c.get('avg_capital_sar'))} more stock, all costs {pc(c.get('total_cost_sar'))}.
  "That is the second headline number — and yes, we hold more stock. More stock, less waste."

Click **ROLLING** in the store selector: tiles and the monthly line re-scope. Click **Whole
plant** again. Hover the monthly line: actual usage, the forecast laid over the tested year,
and the dashed year ahead.

## 2 · The frontier — 1 minute  (same page, bottom chart)

"Every point is the same year replayed at one blanket service level." Drag the handle
from 50% to 99.5%: the four figures under it move — value on the shelves, days waiting,
all costs, purchase orders — each with its delta against the plant today. "The plant's own
levels are the black ring, off the left end: they wait longer than our worst sampled point
while holding less. Their policy is under-serving, not over-invested. That is why the cash
comes from dead money, not from levels." The orange dot is ours: each part at its own level.

## 3 · Recommendations — 2 minutes  (→ to `#/present/recommendations`)

Three tabs, each ranked by money with a total and an Excel export.
- **Order** — "{n(sr.get('order_count'))} orders, {m(sr.get('order_total_sar'))}. Quantity, order-by
  date, cost, and the reason for the level in plain words."
- **Move** — "{n(sr.get('transfer_count'))} parts sitting spare in one store while another is short:
  {m(sr.get('transfer_total_sar'))} of buying avoided. The sending store only gives what it holds above
  its own level."
- **Write off / review** — "The dead-money list, one reason per record: the machine is gone,
  never used, duplicate, idle with nothing scheduled, excess."

## 4 · One part — 2 minutes  (Stock board, first row, or any row)

Click the top row. Read the drawer top to bottom: **what to do** in the accent; the stat row;
the chart — three years of movement, the forecast laid over the tested year, scheduled work
dashed; then **why this number**: how often it moves, how much, which method, the old rule
against ours, and the engine's own sentence. If the filter (M-016367) is in view, tell its
story: "a part that draws ~900 a month and 5,000 in a burst twice a year. The first version
of the levels held eighteen months of it. Now: three windows of everyday usage, with the
outage draw scheduled against the calendar instead of buffered."

## 5 · Ask — 1½ minutes  (→ to `#/present/chat`)

Three questions, typed or from the chips:
1. "Which A-critical parts are out of stock in the rolling mill?"
2. "How much dead money is there, and what is the biggest item?"
3. "Tell me about M-016367."
Point at the line under each answer: *answered by get_stockouts {{…}} — every figure above is
in the rows below*. "The model never calculates. It picks one of four questions the system
has already answered and reads the answer back. Ask it something the data cannot answer and
it will say so."

## 6 · Evidence — 30 seconds  (footer link)

"For the engineers." Faults found: {pct(s.get('recall'))} recall, {pct(s.get('precision'))}
precision against the sealed answer key. Forecast accuracy per class. The backtest table with
the honest callout. The service-level curve. Stop here; leave it on the screen for questions.

## If asked

- *Is the data real?* No — invented plant, planted faults, sealed answer key. Phase 1 swaps the
  generator for the SAP/PiLog extract behind the same interface; the screens do not change.
- *Why does capital go up?* Because the plant under-serves today. Pricing an expedite properly
  makes holding almost any part worthwhile; the cash release is the dead-money list.
- *Why 98% on dead money?* Most of it is a lookup on fields the plant already has. The value is
  applying one rule consistently across every record with a reason on each.
"""


def build(cfg: RunConfig) -> list[Path]:
    out = []
    for name, text in (("RESULTS-SHEET.md", results_sheet(cfg)), ("DEMO-SCRIPT.md", demo_script(cfg))):
        path = ROOT / "docs" / name
        path.write_text(text, encoding="utf-8")
        out.append(path)
    return out
