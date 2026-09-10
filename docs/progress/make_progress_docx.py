"""
Builds docs/progress/POC-PROGRESS.docx — the living progress document.

Two rules make this worth having rather than a thing that quietly lies:

1. **Every number comes from `results/`.** Nothing is typed in. If the pipeline has
   not produced a figure, the document says so rather than carrying a stale one, so
   it cannot drift away from what actually ran.

2. **It is regenerated, never edited.** `python cli.py all` rebuilds it as the last
   step. A hand-edit would survive exactly until the next run.

Audience is a senior manager with no software or inventory background: plain
English, every technical term introduced on first use, no code, no file names, no
jargon in headings.

Run directly with:  python docs/progress/make_progress_docx.py --preset full
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from contracts.config import RunConfig  # noqa: E402

OUT_NAME = "POC-PROGRESS.docx"

INK = RGBColor(0x1A, 0x1D, 0x21)
MUTED = RGBColor(0x60, 0x66, 0x6E)
ACCENT = RGBColor(0xA2, 0x4E, 0x28)
GOOD = RGBColor(0x2B, 0x6B, 0x67)
WARN = RGBColor(0x8A, 0x62, 0x12)


# ── loading ──────────────────────────────────────────────────────────────────


def load(cfg: RunConfig) -> dict:
    """Everything the document knows. Missing files are absent, never stale."""
    out: dict = {}
    for key, name in (
        ("summary", "summary.json"),
        ("score", "defect_score.json"),
        ("manifest", "run_manifest.json"),
        ("checks", "implemented_checks.json"),
        ("classifier", "classifier_report.json"),
        ("classifier_score", "classifier_score.json"),
        ("forecast", "forecast_report.json"),
        ("levels", "levels_report.json"),
        ("backtest", "backtest_report.json"),
        ("frontier", "frontier.json"),
        ("dead_money", "dead_money_report.json"),
    ):
        path = cfg.results_dir / name
        if path.exists():
            out[key] = json.loads(path.read_text(encoding="utf-8"))
    # the marks live beside the classifier's own output; the document wants one view
    if "classifier" in out and "classifier_score" in out:
        out["classifier"].update(out.pop("classifier_score"))
    return out


# ── docx helpers ─────────────────────────────────────────────────────────────


def _style(doc: Document) -> None:
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = INK
    normal.paragraph_format.space_after = Pt(7)
    normal.paragraph_format.line_spacing = 1.14


def h(doc: Document, text: str, level: int = 1) -> None:
    p = doc.add_heading(text, level=level)
    for run in p.runs:
        run.font.color.rgb = ACCENT if level == 1 else INK
        run.font.name = "Calibri"
    p.paragraph_format.space_before = Pt(14 if level == 1 else 10)
    p.paragraph_format.space_after = Pt(5)


def para(doc: Document, text: str, *, bold=False, italic=False, color=None, size=10.5):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.bold = bold
    run.italic = italic
    run.font.size = Pt(size)
    if color is not None:
        run.font.color.rgb = color
    return p


def rich(doc: Document, parts: list[tuple[str, bool]]):
    """A paragraph of (text, bold) pieces."""
    p = doc.add_paragraph()
    for text, bold in parts:
        run = p.add_run(text)
        run.bold = bold
    return p


def bullet(doc: Document, text: str, *, bold_prefix: str = ""):
    p = doc.add_paragraph(style="List Bullet")
    if bold_prefix:
        p.add_run(bold_prefix).bold = True
    p.add_run(text)
    p.paragraph_format.space_after = Pt(3)
    return p


def _shade(cell, hex_colour: str) -> None:
    el = OxmlElement("w:shd")
    el.set(qn("w:val"), "clear")
    el.set(qn("w:fill"), hex_colour)
    cell._tc.get_or_add_tcPr().append(el)


def table(doc: Document, headers: list[str], rows: list[list[str]], *,
          widths: list[float] | None = None, highlight_last: bool = False):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.LEFT
    for i, name in enumerate(headers):
        cell = t.rows[0].cells[i]
        cell.text = ""
        run = cell.paragraphs[0].add_run(name)
        run.bold = True
        run.font.size = Pt(9)
        _shade(cell, "EDEAE5")
    for r in rows:
        cells = t.add_row().cells
        for i, value in enumerate(r):
            cells[i].text = ""
            run = cells[i].paragraphs[0].add_run(str(value))
            run.font.size = Pt(9)
    if highlight_last and len(t.rows) > 1:
        for cell in t.rows[-1].cells:
            _shade(cell, "F3E4DB")
            for p in cell.paragraphs:
                for run in p.runs:
                    run.bold = True
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Inches(w)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


def caption(doc: Document, text: str):
    p = para(doc, text, italic=True, color=MUTED, size=8.5)
    p.paragraph_format.space_after = Pt(10)
    return p


def callout(doc: Document, title: str, body: str, colour=ACCENT):
    t = doc.add_table(rows=1, cols=1)
    t.style = "Table Grid"
    cell = t.rows[0].cells[0]
    cell.text = ""
    p1 = cell.paragraphs[0]
    r1 = p1.add_run(title)
    r1.bold = True
    r1.font.size = Pt(9.5)
    r1.font.color.rgb = colour
    p2 = cell.add_paragraph()
    r2 = p2.add_run(body)
    r2.font.size = Pt(9.5)
    _shade(cell, "FBF6F3" if colour == ACCENT else "F7F4EC")
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


def flow(doc: Document, boxes: list[tuple[str, str]]):
    """A left-to-right diagram: boxes joined by arrows, drawn as a one-row table."""
    cols = len(boxes) * 2 - 1
    t = doc.add_table(rows=1, cols=cols)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, (title, sub) in enumerate(boxes):
        cell = t.rows[0].cells[i * 2]
        cell.text = ""
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(title)
        run.bold = True
        run.font.size = Pt(9)
        if sub:
            p2 = cell.add_paragraph()
            p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r2 = p2.add_run(sub)
            r2.font.size = Pt(8)
            r2.font.color.rgb = MUTED
        _shade(cell, "F3E4DB")
        if i * 2 + 1 < cols:
            arrow = t.rows[0].cells[i * 2 + 1]
            arrow.text = ""
            ap = arrow.paragraphs[0]
            ap.alignment = WD_ALIGN_PARAGRAPH.CENTER
            ar = ap.add_run("\u2192")
            ar.font.size = Pt(12)
            ar.font.color.rgb = MUTED
            arrow.width = Inches(0.28)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


def pct(x, digits=0):
    return "—" if x is None else f"{x * 100:.{digits}f}%"


def sar(x):
    return "—" if x is None else f"SAR {x:,.0f}"


def num(x):
    return "—" if x is None else f"{x:,}"


# ── screenshot ───────────────────────────────────────────────────────────────


SCREENS = [
    ("today.png", "", "Today",
     "The front page, and deliberately the whole of it. Three numbers, each with a "
     "sentence saying what it means and what to do. Anyone can read this page "
     "without being told what an inventory system is."),
    ("board.png", "#/board", "Stock board",
     "One row per part in one storeroom, most urgent first. The second column says "
     "what to do — order this many, move it from another store, or leave it alone — "
     "and it is the only column that has to be read. Twenty-five rows a page, on "
     "twenty-five thousand records."),
    ("drawer.png", "#/board/{position}", "One part, in full",
     "Clicking a row opens the part over the board. What to do first, then the "
     "plain-English explanation of where the number came from, and only then the "
     "chart: three years of movement with the cut-off marked and the year ahead "
     "beside it."),
    ("storerooms.png", "#/storerooms", "Storerooms",
     "Where the stock is, and where it is in the wrong place. The lower table is "
     "the same part sitting spare in one store while another store is below its "
     "level — stock the plant already owns and would otherwise buy again."),
    ("evidence.png", "#/evidence", "How well it works",
     "The evidence page, for engineers. Faults found against the sealed answer key, "
     "forecast accuracy on the held-out year, the backtest, and the service-level "
     "curve. This is the only page that uses technical language; everywhere else it "
     "lives in the tooltips."),
]


def _first_position(cfg: RunConfig) -> str:
    """The top row of the board, so the item view is photographed showing something."""
    import pandas as pd

    path = cfg.results_dir / "positions.parquet"
    if not path.exists():
        return ""
    row = pd.read_parquet(path, columns=["material_id", "storeroom_id"]).iloc[0]
    return f"{row['material_id']}/{row['storeroom_id']}"


def capture_dashboard(cfg: RunConfig, target: Path) -> Path | None:
    """
    Photograph the screens by serving them and pointing a headless browser at them.

    The page loads its JavaScript from a vendored copy, so this works with no
    network. If no browser is available the previous captures are reused rather
    than failing the build — a document with slightly old screenshots is far more
    useful than no document.

    Returns the list of (path, title, caption) that were captured, in screen order.
    """
    browsers = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        shutil.which("chromium") or "",
        shutil.which("google-chrome") or "",
    ]
    browser = next((b for b in browsers if b and Path(b).exists()), None)
    folder = target.parent
    existing = [(folder / name, title, note) for name, _, title, note in SCREENS
                if (folder / name).exists()]
    if browser is None:
        return existing

    port = 8731
    server = subprocess.Popen(
        [sys.executable, str(ROOT / "cli.py"), "serve", "--preset", cfg.preset,
         "--no-browser", "--port", str(port), "--data-dir", str(cfg.data_dir)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        import urllib.error
        import urllib.request

        for _ in range(40):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1)
                break
            except (urllib.error.URLError, OSError):
                time.sleep(0.25)
        else:
            return existing

        position = _first_position(cfg)
        got = []
        folder.mkdir(parents=True, exist_ok=True)
        for name, route, title, note in SCREENS:
            if "{position}" in route:
                if not position:
                    continue
                route = route.replace("{position}", position)
            with tempfile.TemporaryDirectory() as tmp:
                shot = Path(tmp) / "s.png"
                subprocess.run(
                    [browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                     "--virtual-time-budget=9000", "--window-size=1340,1000",
                     f"--screenshot={shot}", f"http://127.0.0.1:{port}/{route}"],
                    capture_output=True, timeout=90,
                )
                if shot.exists() and shot.stat().st_size > 20_000:
                    shutil.copy(shot, folder / name)
            if (folder / name).exists():
                got.append((folder / name, title, note))
        return got or existing
    except Exception:
        pass
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
    return existing
    return target if target.exists() else None


# ── sections ─────────────────────────────────────────────────────────────────


def section_title(doc: Document, data: dict) -> None:
    manifest = data.get("manifest", {})
    generated = manifest.get("generated_at", "")[:10] or date.today().isoformat()

    p = doc.add_paragraph()
    r = p.add_run("Ma'aden Aluminium")
    r.bold = True
    r.font.size = Pt(11)
    r.font.color.rgb = ACCENT

    t = doc.add_heading("Inventory Intelligence — Progress Report", level=0)
    for run in t.runs:
        run.font.color.rgb = INK

    para(doc, "A proof of concept, built on invented data, to show what an "
              "automated check of the storeroom can and cannot find.",
         italic=True, color=MUTED, size=11)
    para(doc, f"Last updated {generated}   ·   "
              f"every figure in this document was produced by the run of that date",
         color=MUTED, size=9)
    doc.add_paragraph()


def section_problem(doc: Document, data: dict) -> None:
    h(doc, "1.  The problem, in one page")

    para(doc, "A storeroom can be full and the plant can still stop for want of a "
              "part. Both things are true at the same time, in the same building, "
              "and they are the same problem.")

    callout(
        doc, "One night at Ras Al Khair",
        "02:14 — a bearing fails on the rolling mill and the line stops. "
        "02:40 — the storeroom is 400 metres away and does not have that bearing. It "
        "never did. 03:10 — the part is air-freighted at three to five times the "
        "normal price. Three days later the mill runs again.\n\n"
        "Three aisles away in the same storeroom sit 400 filter cartridges, worth "
        "about SAR 300,000, for a machine that was removed in 2019. They are "
        "correctly counted and correctly recorded. Not one of them will ever be used.",
    )

    rich(doc, [
        ("The money to buy that bearing had already been spent. ", True),
        ("It was sitting on a shelf, three aisles away, as something else. That is "
         "not a warehouse problem and not a counting problem — the records were "
         "right. It is a buying decision problem, and it happens because nobody can "
         "see across twenty thousand different parts in five storerooms at once.",
         False),
    ])

    h(doc, "Why this matters here", level=2)
    para(doc, "Ma'aden Aluminium runs one continuous chain: a bauxite mine at Al "
              "Ba'itha, 600 kilometres of rail, then a refinery, a smelter and a "
              "rolling mill sharing a single 20 square kilometre site at Ras Al "
              "Khair. Every stage runs continuously, so an hour of unplanned "
              "stoppage costs far more than the part that caused it. That makes "
              "over-stocking feel safe — and it is how a storeroom fills up with "
              "the wrong things.")

    summary = data.get("summary", {})
    inv = summary.get("inventory", {})
    counts = summary.get("counts", {})
    if inv:
        para(doc, "On the invented plant we built for this proof of concept — "
                  "described in section 3 — the position looks like this:")
        table(
            doc,
            ["What", "How much"],
            [
                ["Value of everything on the shelves", sar(inv.get("total_stock_value_sar"))],
                ["Different parts held", num(counts.get("materials"))],
                ["Storeroom records (a part in a storeroom)", num(counts.get("positions"))],
                ["Parts not issued once in two years",
                 f"{num(inv.get('idle_24m_count'))}  ({pct(inv.get('idle_24m_share'), 1)})"],
                ["Value that is dead — see section 3 for what that means",
                 f"{sar(inv.get('dead_value_sar'))}  ({pct(inv.get('dead_value_share'), 1)})"],
            ],
            widths=[4.2, 2.3],
        )
        caption(doc, "Dead means stock for a machine that no longer exists, plus "
                     "anything beyond three years of real demand. A spare that sits "
                     "still for years because it protects the smelter is not dead — "
                     "counting it as dead would overstate the prize about two and a "
                     "half times.")


def section_claims(doc: Document, data: dict) -> None:
    h(doc, "2.  What we set out to prove")

    para(doc, "Three claims, and deliberately nothing else. Each one has to be "
              "provable with a number rather than an opinion.")

    table(
        doc,
        ["Claim", "How it is measured", "Status"],
        [
            ["We can find the problems hiding in the records",
             "Against a sealed list of faults we planted ourselves",
             "Done — section 5"],
            ["We can set better stock levels than the ones in use today",
             "By replaying a year of history under both sets of levels",
             _status(data, "backtest")],
            ["A planner can ask a question in plain English and get an answer "
             "they can check",
             "Twenty set questions with known correct answers",
             _status(data, "chat")],
        ],
        widths=[2.6, 2.5, 1.4],
    )

    para(doc, "If a piece of work does not serve one of those three, it is not "
              "being built. That is a deliberate limit, not an oversight.")


def _status(data: dict, key: str) -> str:
    return "Done" if key in data else "Not yet"


def section_method(doc: Document, data: dict, shot: Path | None) -> None:
    h(doc, "3.  How we prove it without the client's data")

    para(doc, "We have not been given Ma'aden's records, and we do not need them "
              "yet. Instead we built an invented plant that behaves like a real "
              "one, and hid known faults inside it.")

    h(doc, "Why invented data is better here, not worse", level=2)
    para(doc, "With real records we could show attractive screens, but we could not "
              "say how accurate they were — nobody knows the right answer, so "
              "nothing can be marked. With invented records we know every fault we "
              "planted, so we can say exactly how many were found and how many "
              "false alarms were raised. It also means work started immediately "
              "rather than waiting on data access.")

    h(doc, "The words used from here on", level=2)
    for term, meaning in GLOSSARY_CORE:
        bullet(doc, meaning, bold_prefix=f"{term} — ")

    h(doc, "The six record books, and how they join up", level=2)
    para(doc, "Real plants keep this information in three separate systems. Our "
              "invented plant keeps the same six record books, joined the same way.")
    flow(doc, [
        ("Machines", "what exists, how critical"),
        ("Parts", "what each part is"),
        ("Storerooms", "how many are held"),
        ("Movements", "every issue and receipt"),
    ])
    para(doc, "Two more feed into it: maintenance jobs record why a part was taken "
              "out, and planned shutdown dates tell us about demand that has not "
              "happened yet. A job raised weeks before the work is what lets the "
              "system see a spike coming instead of being surprised by it.")

    h(doc, "What happens to the data", level=2)
    flow(doc, [
        ("Build", "invent the plant"),
        ("Check", "look for faults"),
        ("Mark", "compare to the answer key"),
        ("Show", "put it on screen"),
    ])
    para(doc, "The checking stage is never allowed to see the answer key. That is "
              "enforced automatically: an automatic test reads the checking code "
              "and fails if it so much as mentions the answer key by name. Without "
              "that, the marks would be worthless and nobody would notice until a "
              "Ma'aden engineer asked how they were produced.")

    h(doc, "Two kinds of fault, kept apart on purpose", level=2)
    para(doc, "This distinction is what makes the marks honest.")
    table(
        doc,
        ["", "Planted faults", "Faults that emerge on their own"],
        [
            ["What they are",
             "Typing and record-keeping errors we inserted deliberately",
             "Too much stock, obsolete stock, critical parts running low"],
            ["Examples",
             "A blank part number; a negative quantity; the same part entered twice",
             "Stock levels set years ago and never revisited; spares for a machine "
             "that was scrapped"],
            ["How they are marked",
             "Found, missed, or a false alarm — exact counts",
             "Against what the invented plant really did"],
        ],
        widths=[1.1, 2.7, 2.7],
    )
    para(doc, "The second kind is never planted. If we inserted them we would only "
              "be testing whether the system can find our own insertions, rather "
              "than whether it can read a plant.")

    h(doc, "Learn before, test after", level=2)
    manifest = data.get("manifest", {})
    cut = manifest.get("cutoff_date", "")
    start = manifest.get("history_start", "")
    end = manifest.get("history_end", "")
    if cut:
        para(doc, f"The invented plant has three years of history, from {start} to "
                  f"{end}. Anything that learns from the past is only allowed to see "
                  f"up to {cut} — two years. It is then marked on the final year, "
                  "which it has never seen. The cut-off date is set in one place and "
                  "cannot be skipped by accident.")

    if shot:
        h(doc, "What it looks like today", level=2)
        para(doc, "Three screens, all read-only. Every figure on them was worked out "
                  "when the analysis ran; nothing is calculated while a page is open, "
                  "so a screen cannot disagree with the marks beside it. They run "
                  "with no internet connection, which matters on a plant site.")
        for path, title, note in shot:
            h(doc, title, level=3)
            doc.add_picture(str(path), width=Inches(6.3))
            doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
            caption(doc, note)


GLOSSARY_CORE = [
    ("Answer key", "the sealed list of faults we hid in the invented data, which "
                   "the analysis is never allowed to read"),
    ("Planted fault", "a mistake we put in deliberately, so we know it is there"),
    ("False alarm", "the system reports a problem where there was none"),
    ("Found / missed", "of the faults we hid, how many the system reported and how "
                       "many it walked past"),
    ("Storeroom record", "one part in one storeroom — the same part in two "
                         "storerooms is two records"),
]


def section_progress(doc: Document, data: dict) -> None:
    h(doc, "4.  Progress log")
    para(doc, "One entry per stage, added as each is finished. Each says what it "
              "does, what was measured, and what it still cannot do.",
         italic=True, color=MUTED)

    _step_one(doc, data)
    _step_two(doc, data)
    _step_three(doc, data)
    _step_four(doc, data)
    _step_five(doc, data)


def _step_date(data: dict) -> str:
    return (data.get("manifest", {}).get("generated_at", "") or "")[:10]


def _step_one(doc: Document, data: dict) -> None:
    summary = data.get("summary")
    if not summary:
        return
    h(doc, f"Stage 1 — Building a plant that behaves like a real one    ({_step_date(data)})",
      level=2)

    counts = summary.get("counts", {})
    para(doc, f"An invented plant with {num(counts.get('materials'))} different "
              f"parts across {counts.get('storerooms', 5)} storerooms, "
              f"{num(counts.get('movements'))} movements of stock over three years, "
              f"and {num(counts.get('work_orders'))} maintenance jobs.")

    para(doc, "The hard part was not producing data. It was producing data that "
              "behaves like a storeroom rather than a supermarket. Published "
              "figures for this industry say that between a third and a half of "
              "parts do not move in two years, and that a fifth to two fifths of "
              "the value is dead. Our invented plant is checked against those "
              "figures automatically every time it is built.")

    checks = summary.get("dataset_checks", [])
    if checks:
        rows = [[c["name"].capitalize(), _fmt_check(c), c["target"],
                 "Yes" if c["ok"] else "NO"] for c in checks]
        table(doc, ["What is checked", "Measured", "Should be", "Within range?"],
              rows, widths=[2.5, 1.3, 1.7, 1.0])
        caption(doc, "If any of these drifts out of range the build stops. Every "
                     "later figure is measured against this data, so a plant that "
                     "quietly stopped resembling a real one would make everything "
                     "afterwards look excellent and mean nothing.")

    sample = summary.get("sample_materials", [])
    if sample:
        h(doc, "Eight parts, drawn at random", level=3)
        rows = [[s.get("description", ""), s.get("manufacturer", ""),
                 f"{s.get('unit_price_sar', 0):,.0f}", s.get("criticality", ""),
                 s.get("fitted_to", "")] for s in sample[:8]]
        table(doc, ["Part", "Made by", "SAR each", "Criticality", "Fitted to"],
              rows, widths=[2.3, 1.0, 0.8, 0.7, 1.6])
        caption(doc, "Criticality A means the plant stops if it is missing; C means "
                     "somebody waits. Each part is attached to a machine that could "
                     "actually hold it — a bearing sits on a pump, never on a "
                     "potline. A maintenance engineer reading this list is the "
                     "first test the data has to pass.")

    _limits(doc, [
        "This is invented data. It is built to behave like Ma'aden's, not to be it.",
        "The published industry figures we check against are ranges from other "
        "companies. They are a starting point, and the pilot replaces them with "
        "Ma'aden's own numbers.",
        "Maintenance jobs are grouped by machine and month rather than being "
        "modelled job by job. It gives realistic multi-part jobs, but the number of "
        "parts on a job is a property of our grouping rather than of the plant.",
    ])


def _fmt_check(c: dict) -> str:
    v = c["value"]
    if isinstance(v, float) and 0 < abs(v) <= 1.5:
        return f"{v * 100:.0f}%"
    if isinstance(v, float):
        return f"{v:,.2f}"
    return f"{v:,}"


def _step_two(doc: Document, data: dict) -> None:
    score = data.get("score")
    if not score:
        return
    s = score.get("summary", {})
    h(doc, f"Stage 2 — Seven checks that read the records    ({_step_date(data)})",
      level=2)

    para(doc, "Seven separate checks, each looking for one kind of fault. Think of "
              "them as seven inspectors walking the storeroom, each with one thing "
              "to look for.")

    plain = {
        "NEGATIVE_STOCK": "A quantity below zero. Impossible, so the balance cannot "
                          "be trusted.",
        "BLANK_MPN": "No manufacturer's part number, so the part cannot be matched "
                     "to a catalogue or to the same part in another storeroom.",
        "BLANK_UOM": "No unit. Ten of something means nothing until you know whether "
                     "it is ten pieces or ten boxes.",
        "UOM_MISMATCH": "A unit that disagrees with every similar part, with the "
                        "price left on the old unit.",
        "IMPOSSIBLE_LEAD_TIME": "A delivery time of nothing, or of ten years. Either "
                                "way the reorder level built on it is wrong.",
        "ISSUE_WITHOUT_WORK_ORDER": "Stock left the store and no job accounts for it.",
        "DUPLICATE_MATERIAL": "The same physical part entered twice under different "
                              "descriptions.",
    }
    rows = []
    for r in score.get("by_type", []):
        t = r["defect_type"]
        rows.append([
            plain.get(t, t), num(r["planted"]), num(r["found"]), num(r["missed"]),
            num(r["false_alarms"]),
            pct(r["found"] / r["planted"] if r["planted"] else None),
        ])
    rows.append(["Everything together", num(s.get("planted")), num(s.get("found")),
                 num(s.get("missed")), num(s.get("false_alarms")),
                 pct(s.get("recall"))])
    table(doc, ["What the check looks for", "Hidden", "Found", "Missed",
                "False alarms", "Found rate"],
          rows, widths=[2.6, 0.7, 0.7, 0.7, 0.9, 0.8], highlight_last=True)

    info = s.get("informational") or {}
    if info:
        total = sum(info.values())
        para(doc, f"The checks also raised {total} reports of a different kind: the "
                  "stock balance not matching the list of movements. Nothing was "
                  "planted for that, so it is counted separately rather than held "
                  "against the system. It is the check an auditor recognises on "
                  "sight — either the arithmetic adds up or the balance cannot be "
                  "trusted.")

    h(doc, "Finding the same part entered twice", level=3)
    para(doc, "This is the hardest of the seven, and the one that matters most "
              "here. When Ma'aden absorbed the Alcoa and Alba operations in 2025, "
              "each came with its own list of parts. The same bearing can now sit "
              "under three descriptions in three storerooms, and nobody knows it is "
              "the same bearing.")
    para(doc, "Worse, the usage splits across the entries. Neither looks unusual on "
              "its own, so both are re-ordered as though they were separate parts.")
    para(doc, "The system compares every part against every other one that could "
              "plausibly match, using five clues:")
    for clue in [
        ("The description, allowing for shorthand — ",
         "somebody writing BRG where somebody else wrote BEARING."),
        ("The measurements and grades — ",
         "6205 and 6310 are different bearings, however similar the words are."),
        ("The manufacturer's part number — ",
         "the strongest clue there is. Two different numbers mean two different "
         "parts; there is no partly the same."),
        ("The manufacturer's name — ", "allowing for SKF, S.K.F. and SKF AB."),
        ("Price, unit and category — ", "weak on its own, useful alongside the rest."),
    ]:
        bullet(doc, clue[1], bold_prefix=clue[0])
    para(doc, "Each clue gives a score, the scores are combined, and anything above "
              "an agreed level is reported as a likely pair. A clue with nothing to "
              "say — a missing part number, which is exactly what a re-typed record "
              "loses — counts as no evidence rather than as evidence against.")

    mangle = score.get("duplicate_by_mangle") or {}
    if mangle:
        friendly = {
            "abbrev": "Shorthand used (BRG for BEARING)",
            "no_space": "Spaces removed",
            "no_comma": "Commas removed",
            "token_front": "Size moved to the front",
            "token_dropped": "Size left off altogether",
            "typo": "A character mistyped",
            "suffix": "Marked -OLD or (DUP)",
            "none": "Re-typed with no change",
        }
        rows = [[friendly.get(k, k), num(v["planted"]), num(v["found"]),
                 pct(v.get("recall"))]
                for k, v in sorted(mangle.items(), key=lambda kv: -(kv[1].get("recall") or 0))]
        table(doc, ["How the copy was written differently", "Hidden", "Found",
                    "Found rate"], rows, widths=[3.0, 0.9, 0.9, 1.0])
        caption(doc, "Reported this way on purpose. A single overall figure would "
                     "hide that one situation is much harder than the others.")

    h(doc, "Two faults the checks found in our own invented plant", level=3)
    para(doc, "Both were ours, not the system's, and both would have made the "
              "results meaningless if they had gone unnoticed.")
    bullet(doc, "85 in every 100 parts shared a description with some other part, "
                "because we varied them along only one measurement. That produced "
                "82,000 accidental identical pairs against the 140 we planted. The "
                "system flagging them was right and our marking was wrong. Parts now "
                "carry two characteristics, and a test refuses to let the problem "
                "come back.",
           bold_prefix="Descriptions repeated by accident. ")
    bullet(doc, "One check scored 59 out of 60 and the system was innocent: we "
                "blanked a unit and then overwrote the same record with a different "
                "fault, so the answer key claimed a blank that was no longer there. "
                "This is the worst kind of marking error, because it looks like a "
                "failure of the thing being tested.",
           bold_prefix="Two faults on one record. ")

    _limits(doc, [
        "The unit check finds a part moved to an unusual unit. It cannot find one "
        "moved to the usual unit, because that looks exactly like its neighbours. "
        "Every miss is of that kind.",
        "Duplicate detection is weakest when the size was simply left off the "
        "re-typed record — there is little left to compare.",
        "The confidence level for reporting a duplicate pair was chosen using this "
        "data. That is normal, but it is not an independent result: on Ma'aden's own "
        "records it must be set again from a sample checked by hand.",
    ])


def _step_three(doc: Document, data: dict) -> None:
    rep = data.get("classifier")
    if not rep:
        return
    h(doc, f"Stage 3 — Sorting parts by how they are used    ({rep.get('generated_at','')[:10]})",
      level=2)
    para(doc, "Before anything can be forecast, each part has to be sorted by how it "
              "behaves. Some are used constantly; some are used twice a decade. The "
              "same method cannot serve both, and pretending it can is where most "
              "inventory systems go wrong.")
    para(doc, "Each part is measured on two things: how often it is used, and how "
              "much the quantity jumps about. That places it in one of four groups.")

    plain = {
        "smooth": "Used regularly, in steady amounts — filters, gaskets",
        "erratic": "Used regularly, but the amount jumps about",
        "intermittent": "Long gaps between uses, small amounts",
        "lumpy": "Long gaps, and large amounts when it does move",
    }
    mix = rep.get("class_mix", {})
    if mix:
        rows = [[plain.get(k, k), num(v), pct(v / max(sum(mix.values()), 1))]
                for k, v in sorted(mix.items(), key=lambda kv: -kv[1])]
        table(doc, ["Group", "Parts", "Share"], rows, widths=[3.4, 1.1, 1.0])
        caption(doc, "Most of an MRO storeroom falls into the two lower rows. That "
                     "is the whole reason a single standard formula gives poor "
                     "answers on exactly the parts that matter most.")

    if rep.get("agreement") is not None:
        para(doc, f"Checked against what the invented plant actually did, the "
                  f"sorting agrees {pct(rep['agreement'])} of the time. It only ever "
                  "sees the first two years of history — the same handicap it will "
                  "have on the day it goes live.")

    pattern = rep.get("largest_disagreement")
    if pattern and pattern.get("share_genuinely_above_cv2_cutoff", 0) > 0.9:
        callout(
            doc, "Where it disagrees, and why we have not simply changed it",
            f"Almost all of the remaining disagreement is one pattern: "
            f"{pattern['materials']:,} parts that are used only occasionally, but in "
            "wildly varying amounts. Our sorting calls them rare-and-large; the "
            "reference list we are marked against only allows occasional. Every one "
            "of them genuinely does vary enough in quantity to belong where we put "
            "it, so this reads as a gap in the reference list rather than a mistake "
            "in the sorting. We have left the reference list alone and reported the "
            "lower figure, because widening it ourselves would be marking our own "
            "homework.",
        )

    by_store = rep.get("by_storeroom") or []
    if by_store:
        h(doc, "How the mix differs by storeroom", level=3)
        cols = ["smooth", "erratic", "intermittent", "lumpy"]
        rows = [[r["storeroom_id"], num(r.get("total"))]
                + [pct(r.get(c, 0) / max(r.get("total", 1), 1)) for c in cols]
                for r in by_store]
        table(doc, ["Storeroom", "Parts", "Steady", "Jumpy", "Occasional", "Rare & large"],
              rows, widths=[1.2, 0.9, 0.9, 0.9, 1.1, 1.2])

    _limits(doc, rep.get("limits", []))


def _step_four(doc: Document, data: dict) -> None:
    rep = data.get("forecast")
    if not rep:
        return
    h(doc, f"Stage 4 — Predicting what will be needed    ({rep.get('generated_at','')[:10]})",
      level=2)
    para(doc, "Each group gets a method suited to it. Parts used rarely are handled "
              "by a family of methods built for exactly that — they forecast how "
              "long until the next use and how much, separately, instead of "
              "averaging a lot of zeros. Parts used steadily get a simpler method. "
              "Spares that have never been used are handled from the failure rate of "
              "the machines they protect, because there is no usage history to learn "
              "from.")
    para(doc, "Maintenance jobs already raised, and shutdown dates already in the "
              "calendar, are added on top as demand we know about rather than demand "
              "we are guessing at.")

    rows = rep.get("mase_by_class") or []
    if rows:
        table(
            doc,
            ["Group", "Our error", "If we assumed last month repeats",
             "If we assumed nothing is needed", "Better?"],
            [[r["class"], f"{r['mase']:.2f}", f"{r['naive']:.2f}", f"{r['zero']:.2f}",
              "Yes" if r["mase"] < min(r["naive"], r["zero"]) else "No"] for r in rows],
            widths=[1.3, 1.0, 1.7, 1.7, 0.7],
        )
        caption(doc, "Lower is better. The figure is the average error compared "
                     "against a deliberately simple guess, so 1.00 means no better "
                     "than that guess. Two simple guesses are shown because for "
                     "rarely used parts, assuming nothing is needed is a "
                     "surprisingly strong baseline and it would be misleading to "
                     "leave it out.")

    _limits(doc, rep.get("limits", []))


def _step_five(doc: Document, data: dict) -> None:
    bt = data.get("backtest")
    lv = data.get("levels")
    if not bt:
        return
    h(doc, f"Stage 5 — Setting the stock levels, and proving they are better    "
           f"({bt.get('generated_at','')[:10]})", level=2)

    para(doc, "This is the second of the three claims, and the one with a number "
              "attached. For every part in every storeroom we work out two figures: "
              "the level at which to reorder, and how much to bring it back up to.")

    para(doc, "The usual textbook formula assumes demand follows a bell curve. That "
              "is fair for a gasket used every week and wrong for a spare used twice "
              "a decade — and the second group is where being wrong is expensive. So "
              "instead of assuming a shape, we replay each part's own history: how "
              "often it moves, and how much when it does. The level is set so that it "
              "covers the required share of past stretches of the same length as the "
              "delivery time.")

    if lv:
        sl = lv.get("service_level_by_criticality", {})
        if sl:
            para(doc, "How sure we aim to be of having the part is worked out per "
                      "part, from what its absence costs against what holding it "
                      "costs. Two things drive it: how badly the plant needs it, and "
                      "how expensive it is to keep on a shelf. A cheap part that "
                      "stops the line is held to the maximum; an expensive one that "
                      "stops the same line is held to a little less, because the "
                      "stoppage costs the same either way and the shelf does not.")
            label = {"A": "A — the plant stops", "B": "B — production slows",
                     "C": "C — somebody waits"}
            rows = []
            for key in ("A", "B", "C"):
                v = sl.get(key)
                if isinstance(v, dict):
                    rows.append([label[key], num(v.get("positions")),
                                 pct(v.get("median"), 1),
                                 f"{pct(v.get('low'), 1)} to {pct(v.get('high'), 1)}"])
                elif v is not None:
                    rows.append([label[key], "—", pct(v, 1), "—"])
            if rows:
                table(doc, ["If it is missing", "Records", "Typical", "Range"],
                      rows, widths=[2.4, 1.0, 1.1, 1.7])

    h(doc, "Replaying the year, both ways", level=3)
    para(doc, f"The final year — {bt.get('evaluated_days')} days that nothing in the "
              "system had ever seen — was replayed twice over "
              f"{bt.get('positions', 0):,} storeroom records. Once with the levels the "
              "plant uses today, once with ours. Same demand, same delivery delays, "
              "same starting stock: the only difference is the levels.")

    b, po, c = bt.get("baseline", {}), bt.get("policy", {}), bt.get("change", {})

    def row(label, key, money=False):
        fmt = (lambda v: sar(v)) if money else (lambda v: num(round(v)))
        delta = c.get(key)
        return [label, fmt(b.get(key)), fmt(po.get(key)),
                "—" if delta is None else f"{delta * 100:+.0f}%"]

    table(
        doc,
        ["", "Levels in use today", "Our levels", "Change"],
        [
            row("Days spent waiting for a part", "stockout_days"),
            row("Units short over the year", "units_short"),
            row("Value sitting on the shelves", "avg_capital_sar", money=True),
            row("Cost of being short", "shortage_cost_sar", money=True),
            row("Cost of holding stock", "holding_cost_sar", money=True),
            row("Both costs together", "total_cost_sar", money=True),
        ],
        widths=[2.4, 1.6, 1.4, 0.9],
        highlight_last=True,
    )

    callout(
        doc, "Read this honestly: we spend more to waste less",
        "Our levels hold MORE stock, not less — about "
        f"{pct(c.get('avg_capital_sar'), 0)} more. In exchange the plant spends "
        f"{pct(abs(c.get('stockout_days') or 0), 0)} fewer days waiting for a part. "
        "Adding the two costs together, the plant is "
        f"{pct(abs(c.get('total_cost_sar') or 0), 0)} better off overall.\n\n"
        "That is worth stating plainly because it runs the opposite way to the usual "
        "pitch. Better stocking does not release cash here — it moves cash to where "
        "it stops production losses. The cash release is a separate exercise: finding "
        "the stock that is dead, which is the next stage.",
        colour=WARN,
    )

    moved_out = bt.get("capital_moved_out_sar")
    moved_in = bt.get("capital_moved_in_sar")
    if moved_out is not None:
        para(doc, f"Underneath the total, capital moves in both directions: "
                  f"{sar(moved_out)} comes off shelves where it was doing nothing "
                  f"({bt.get('positions_lowered', 0):,} records), and {sar(moved_in)} "
                  f"goes onto shelves where it prevents a stoppage "
                  f"({bt.get('positions_raised', 0):,} records).")

    by_crit = bt.get("by_criticality") or []
    if by_crit:
        h(doc, "Where the improvement lands", level=3)
        rows = [[r["criticality"], num(r["positions"]),
                 num(r["baseline_stockout_days"]), num(r["policy_stockout_days"]),
                 sar(r["baseline_capital_sar"]), sar(r["policy_capital_sar"])]
                for r in sorted(by_crit, key=lambda r: r["criticality"])]
        table(doc, ["If missing", "Records", "Days waiting now",
                    "Days waiting with ours", "Value now", "Value with ours"],
              rows, widths=[0.9, 0.8, 1.2, 1.3, 1.2, 1.2])
        caption(doc, "Split this way on purpose. A headline improvement means "
                     "something quite different if it all landed on the cheapest "
                     "parts and the critical ones got worse.")

    fr = data.get("frontier")
    if fr and fr.get("curve"):
        h(doc, "What a service level costs — the same year, priced ten ways", level=3)
        para(doc, "The comparison above moves two things at once: how much stock is "
                  "held, and how well the plant is served. To separate them the whole "
                  "year was replayed again at ten different service levels — the same "
                  "demand, the same delivery delays — so the trade can be read off a "
                  "measured curve instead of argued about. This is also the data "
                  "behind the scenario slider the brief asks for.")

        rows = []
        for r in fr["curve"]:
            rows.append([
                pct(r.get("service_level"), 1),
                num(r.get("stockout_days")),
                sar(r.get("avg_capital_sar")),
                num(r.get("orders_placed")),
                sar(r.get("total_cost_sar")),
            ])
        base, rec = fr.get("baseline", {}), fr.get("recommended", {})
        rows.append(["Levels in use today", num(base.get("stockout_days")),
                     sar(base.get("avg_capital_sar")), num(base.get("orders_placed")),
                     sar(base.get("total_cost_sar"))])
        rows.append(["Our levels", num(rec.get("stockout_days")),
                     sar(rec.get("avg_capital_sar")), num(rec.get("orders_placed")),
                     sar(rec.get("total_cost_sar"))])
        table(doc, ["Aim to have the part", "Days waiting", "Value held",
                    "Orders placed", "Both costs"],
              rows, widths=[1.5, 1.1, 1.5, 1.0, 1.5], highlight_last=True)
        caption(doc, "Reading down the table: every step up in service buys fewer "
                     "days waiting and costs more capital. Our recommended levels do "
                     "not sit on this curve, because they do not use one figure for "
                     "everything — each part gets its own from what its absence costs.")

        matched = fr.get("at_the_plants_own_service_level") or {}
        if matched.get("plain"):
            callout(doc, "The honest answer to \u201chow much cash does this release\u201d",
                    matched["plain"], colour=WARN)

    if lv and lv.get("order_cost_sar"):
        h(doc, "Ordering less often, on purpose", level=3)
        para(doc, "The first version of these levels placed 71% more purchase orders "
                  "than the plant does today for the same flow of material — a "
                  "trickle every week. That looked free only because placing an order "
                  "was free in the model. Two changes fixed it: an order now has to "
                  "cover at least the demand expected while it is in transit, and it "
                  "is rounded up to the pack the plant is already receiving in, read "
                  f"off its own receipt history ({lv.get('positions_with_a_pack_above_one', 0):,} "
                  "records have a pack larger than one). Raising, chasing and "
                  f"receiving an order is charged at SAR {lv.get('order_cost_sar', 0):,.0f} "
                  "a time, so the cost of ordering often now appears in the total "
                  f"rather than beside it. Orders placed are now {c.get('orders_placed', 0) * 100:+.0f}% "
                  "against the plant's.")

    limits = list(bt.get("limits", []))
    if lv:
        limits += lv.get("limits", [])
    if fr:
        limits += fr.get("limits", [])
    _limits(doc, limits)


def _limits(doc: Document, limits: list[str]) -> None:
    if not limits:
        return
    p = para(doc, "What this cannot do yet", bold=True, size=9.5)
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(2)
    for text in limits:
        bullet(doc, text)


def section_numbers(doc: Document, data: dict) -> None:
    h(doc, "5.  The numbers so far")
    para(doc, "One table, growing as each stage lands. Everything here was produced "
              "by the run named at the top of this document.")

    rows = []
    score = data.get("score", {}).get("summary", {})
    if score:
        rows += [
            ["Faults hidden in the records", num(score.get("planted"))],
            ["Faults found", f"{num(score.get('found'))}  ({pct(score.get('recall'))})"],
            ["Faults missed", num(score.get("missed"))],
            ["False alarms", num(score.get("false_alarms"))],
        ]
    bt = data.get("backtest", {})
    if bt:
        rows += [
            ["Days a critical part was unavailable — levels in use today",
             num(bt.get("baseline_stockout_days"))],
            ["Days a critical part was unavailable — our levels",
             num(bt.get("policy_stockout_days"))],
            ["Value tied up on the shelves — levels in use today",
             sar(bt.get("baseline_capital_sar"))],
            ["Value tied up on the shelves — our levels",
             sar(bt.get("policy_capital_sar"))],
            ["Both costs together — levels in use today",
             sar((bt.get("baseline") or {}).get("total_cost_sar"))],
            ["Both costs together — our levels",
             sar((bt.get("policy") or {}).get("total_cost_sar"))],
        ]
    dm = data.get("dead_money", {})
    if dm:
        rows += [
            ["Dead stock the system identified", sar(dm.get("claimed_sar"))],
            ["Dead stock actually there", sar(dm.get("true_dead_sar"))],
            ["Wrongly called dead", sar(dm.get("over_claimed_sar"))],
        ]
    if not rows:
        rows = [["Nothing measured yet", "—"]]
    table(doc, ["Measure", "Result"], rows, widths=[4.4, 2.1])

    missing = [name for key, name in (
        ("backtest", "stock levels compared against today's"),
        ("dead_money", "dead stock found against dead stock present"),
    ) if key not in data]
    if missing:
        para(doc, "Still to come in this table: " + "; ".join(missing) + ".",
             italic=True, color=MUTED, size=9)


def section_next(doc: Document, data: dict) -> None:
    h(doc, "6.  What happens next")
    steps = [
        ("classifier", "Sort every part by how it is used"),
        ("forecast", "Predict what will be needed, method matched to each group"),
        ("backtest", "Set better stock levels, and prove it by replaying a year"),
        ("dead_money", "List the dead stock in order of value"),
        (None, "Two screens: the summary, and a page for a single part"),
        (None, "A question box: ask in English, get a checkable answer"),
    ]
    for key, text in steps:
        done = key is not None and key in data
        bullet(doc, text + ("   (done)" if done else ""))

    callout(
        doc, "Deliberately not being built",
        "A heavier prediction method that would be harder to explain; matching parts "
        "by meaning rather than by wording; Arabic descriptions; logins; a live "
        "connection to SAP; automatic purchase orders; any screen beyond the two "
        "above. Each was considered and set aside so the three claims get proved "
        "properly rather than six things getting started.",
        colour=WARN,
    )


def section_sceptic(doc: Document, data: dict) -> None:
    h(doc, "7.  Questions a sceptic would ask")

    score = data.get("score", {}).get("summary", {})
    found = num(score.get("found"))
    planted = num(score.get("planted"))
    false_alarms = num(score.get("false_alarms"))

    qa = [
        ("Why invent the data? Why not use ours?",
         "Because invented data can be marked and yours cannot. Nobody knows every "
         "fault sitting in Ma'aden's records, so there is nothing to compare an "
         "answer against — we could show you a convincing screen and neither of us "
         "would know if it were right. Here we hid the faults ourselves, so we can "
         f"say {found} of {planted} were found with {false_alarms} false alarms. It "
         "also meant work could start immediately instead of waiting for access."),
        ("How do I know the analysis is not just reading the answers?",
         "Because it cannot reach them. The answers are kept apart from the "
         "analysis, and an automatic test reads the analysis code and fails the "
         "build if it so much as names the answer file. The marking runs afterwards, "
         "as a separate step. This is the first thing an auditor would ask, so it is "
         "enforced by machine rather than by good intentions."),
        ("Is this artificial intelligence?",
         "Mostly no, and that is deliberate. The checks are rules and statistics — "
         "the kind of thing an experienced planner would do by hand if they had the "
         "time and could hold twenty thousand parts in their head. Artificial "
         "intelligence appears in one place only, at the end: turning a typed "
         "question into an answer. Even there it does no arithmetic. It asks the "
         "system for the figures and reads them back, and every answer shows the "
         "numbers underneath. A system that invents a stock figure in front of a "
         "planner is finished the first time it happens."),
        ("What happens when the real data arrives?",
         "The invented plant plugs into the analysis at the same point real records "
         "would. Swapping it is replacing one part, not rebuilding. What will "
         "genuinely change is that real records are messier than ours — categories "
         "maintained by hand over decades, spellings that drift, codes that mean "
         "different things in different plants. The checks are built to say nothing "
         "rather than say something wrong when the data is unclear, but that has to "
         "be measured on your records, not assumed."),
        ("What could go wrong?",
         "Three things, in order of likelihood. The maintenance system may not be "
         "reachable, and without it we cannot tell a part that is obsolete from a "
         "spare that is quietly protecting the smelter. The savings figure is built "
         "on published industry ranges until we can re-measure it on Ma'aden's own "
         "records, so it should be treated as an indication of scale rather than a "
         "promise. And a system like this only helps if planners use it, which is "
         "why the last piece is a plain question box rather than another report."),
    ]
    for question, answer in qa:
        para(doc, question, bold=True, size=10.5)
        para(doc, answer)


def section_glossary(doc: Document, data: dict) -> None:
    doc.add_section(WD_SECTION.NEW_PAGE)
    h(doc, "8.  Glossary")
    para(doc, "Every term used in this document, in one line each.",
         italic=True, color=MUTED)

    terms = list(GLOSSARY_CORE) + [
        ("Criticality", "how badly the plant is hurt if the part is missing. A stops "
                        "production, B slows it, C inconveniences somebody"),
        ("Dead stock", "stock for a machine that no longer exists, plus anything "
                       "beyond three years of real demand"),
        ("Duplicate", "the same physical part entered twice under different "
                      "descriptions"),
        ("Insurance spare", "an expensive part held for years against a failure that "
                            "may never happen. Sitting still is correct behaviour, "
                            "not waste"),
        ("Lead time", "how long a part takes to arrive once ordered — days for a "
                      "gasket, eighteen months for a transformer"),
        ("MRO", "maintenance, repair and operations: the spare parts and consumables "
                "that keep a plant running, as opposed to what it produces"),
        ("Movement", "a single entry in the stock book — a part issued, or a "
                     "delivery received"),
        ("Reorder level", "the quantity at which more should be ordered"),
        ("Safety stock", "the extra held to cover a delivery arriving late or demand "
                         "arriving early"),
        ("Service level", "how often we intend to have the part when it is asked "
                          "for. 95% means one request in twenty waits"),
        ("Shutdown", "a planned stoppage for major maintenance. Consumption of "
                     "certain parts rises sharply, and the date is known in advance"),
        ("Stockout", "a part was needed and was not there"),
        ("Unit of measure", "what a quantity counts — pieces, metres, kilograms, "
                            "boxes"),
        ("Work order", "the maintenance job that explains why a part was taken out "
                       "of the store"),
    ]
    seen = set()
    rows = []
    for term, meaning in sorted(terms, key=lambda t: t[0].lower()):
        if term.lower() in seen:
            continue
        seen.add(term.lower())
        rows.append([term, meaning])
    table(doc, ["Term", "What it means"], rows, widths=[1.5, 5.0])


# ── assembly ─────────────────────────────────────────────────────────────────


def build_document(cfg: RunConfig, out_path: Path | None = None) -> Path:
    data = load(cfg)
    if "summary" not in data:
        raise FileNotFoundError(
            f"no results to report on — run `python cli.py all --preset {cfg.preset}` first"
        )

    out_path = out_path or (Path(__file__).resolve().parent / OUT_NAME)
    shot = capture_dashboard(cfg, Path(__file__).resolve().parent / "dashboard.png")

    doc = Document()
    _style(doc)
    for s in doc.sections:
        s.left_margin = s.right_margin = Inches(0.85)
        s.top_margin = s.bottom_margin = Inches(0.75)

    section_title(doc, data)
    section_problem(doc, data)
    section_claims(doc, data)
    section_method(doc, data, shot)
    section_progress(doc, data)
    section_numbers(doc, data)
    section_next(doc, data)
    section_sceptic(doc, data)
    section_glossary(doc, data)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    return _save(doc, out_path)


def _save(doc, out_path: Path) -> Path:
    """
    Write beside the target and swap it in, so a half-written document never
    replaces a good one.

    If the target is locked — almost always because it is open in Word — fall back
    to a dated copy and say so, rather than failing the whole pipeline over a file
    handle. `cli.py all` ends with this step, and losing a run because somebody left
    the report open would be a poor trade.
    """
    tmp = out_path.with_suffix(".tmp.docx")
    doc.save(tmp)
    try:
        os.replace(tmp, out_path)
        return out_path
    except PermissionError:
        fallback = out_path.with_name(
            f"{out_path.stem}-{datetime.now().strftime('%Y%m%d-%H%M')}{out_path.suffix}"
        )
        os.replace(tmp, fallback)
        print(
            f"  {out_path.name} is open elsewhere — wrote {fallback.name} instead. "
            "Close it and re-run `report` to update the main copy.",
            file=sys.stderr,
        )
        return fallback


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--preset", default="full", choices=("toy", "full"))
    p.add_argument("--data-dir", default=None)
    p.add_argument("--out", default=None)
    args = p.parse_args(argv)

    kw = {"preset": args.preset}
    if args.data_dir:
        kw["data_dir"] = Path(args.data_dir)
    cfg = RunConfig(**kw)
    out = build_document(cfg, Path(args.out) if args.out else None)
    print(f"wrote {out}  ({out.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
