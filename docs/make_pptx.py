"""
Generates the 4-slide Ma'aden MRO pitch as a real, editable .pptx.

Mirrors docs/pitch.html: same content, same bauxite-on-aluminium palette, same
slide order. Every element is a native PowerPoint shape (no images), so the deck
can be edited in PowerPoint after generation.

Fonts are deliberately Windows-safe (Segoe UI / Consolas) rather than the web
deck's Archivo / IBM Plex Mono, which are unlikely to be installed on a client
machine and would silently fall back to something worse.

Run:  python make_pptx.py
"""

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

# ── palette (matches pitch.html light theme) ─────────────────────────────
INK       = RGBColor(0x16, 0x19, 0x1C)
INK2      = RGBColor(0x40, 0x45, 0x4B)
MUTED     = RGBColor(0x78, 0x7D, 0x85)
LINE      = RGBColor(0xDF, 0xDA, 0xD3)
LINE2     = RGBColor(0xC7, 0xC0, 0xB7)
PANEL     = RGBColor(0xF5, 0xF3, 0xF0)
PANEL2    = RGBColor(0xED, 0xEA, 0xE5)
WHITE     = RGBColor(0xFF, 0xFF, 0xFF)
ACCENT    = RGBColor(0xA2, 0x4E, 0x28)   # bauxite
ACC_SOFT  = RGBColor(0xF5, 0xE7, 0xDF)
TEAL      = RGBColor(0x2B, 0x6B, 0x67)
TEAL_SOFT = RGBColor(0xE0, 0xEB, 0xEA)
WARN      = RGBColor(0x8C, 0x64, 0x12)
WARN_SOFT = RGBColor(0xF4, 0xEB, 0xD6)
# flow ramp: one hue, four steps
F1, F2 = RGBColor(0xEF, 0xE0, 0xD6), RGBColor(0xDC, 0xB7, 0x9E)
F3, F4 = RGBColor(0xC0, 0x80, 0x55), RGBColor(0xA2, 0x4E, 0x28)

SANS = "Segoe UI"
MONO = "Consolas"

# 16:9 at 13.333 x 7.5 in
SW, SH = Inches(13.333), Inches(7.5)
MARGIN = Inches(0.62)
CONTENT_W = SW - 2 * MARGIN


# ── primitives ───────────────────────────────────────────────────────────
def box(slide, x, y, w, h, fill=None, line=None, line_w=0.75):
    s = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, x, y, w, h)
    s.shadow.inherit = False
    if fill is None:
        s.fill.background()
    else:
        s.fill.solid()
        s.fill.fore_color.rgb = fill
    if line is None:
        s.line.fill.background()
    else:
        s.line.color.rgb = line
        s.line.width = Pt(line_w)
    s.text_frame.word_wrap = True
    return s


def accent_bar(slide, x, y, w, h, color):
    """Thin coloured rule used as a top or left edge marker."""
    return box(slide, x, y, w, h, fill=color)


def text(slide, x, y, w, h, runs, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP,
         line_spacing=1.0, space_after=0):
    """runs: list of paragraphs; each is a list of (txt, size, bold, color, font)."""
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    for i, para in enumerate(runs):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = line_spacing
        p.space_after = Pt(space_after)
        for (txt, size, bold, color, font) in para:
            r = p.add_run()
            r.text = txt
            r.font.size = Pt(size)
            r.font.bold = bold
            r.font.color.rgb = color
            r.font.name = font
    return tb


def t(txt, size=12, bold=False, color=INK, font=SANS):
    return (txt, size, bold, color, font)


def label(slide, x, y, w, txt, color=MUTED):
    return text(slide, x, y, w, Inches(0.2),
                [[t(txt.upper(), 8, True, color, SANS)]])


def slide_head(slide, num, title, kicker):
    """Numbered header with the 2pt rule underneath, as in the web deck."""
    box(slide, MARGIN, Inches(0.52), Inches(0.42), Inches(0.28),
        fill=None, line=LINE2)
    text(slide, MARGIN, Inches(0.57), Inches(0.42), Inches(0.2),
         [[t(num, 9, True, ACCENT, MONO)]], align=PP_ALIGN.CENTER)
    text(slide, MARGIN + Inches(0.6), Inches(0.44), CONTENT_W - Inches(0.6), Inches(0.42),
         [[t(title, 25, True, INK, SANS)]])
    text(slide, MARGIN + Inches(0.6), Inches(0.86), CONTENT_W - Inches(0.6), Inches(0.24),
         [[t(kicker, 11, False, MUTED, SANS)]])
    accent_bar(slide, MARGIN, Inches(1.20), CONTENT_W, Pt(1.6), INK)


def foot(slide, left, right):
    text(slide, MARGIN, SH - Inches(0.42), CONTENT_W, Inches(0.2),
         [[t(left.upper(), 7.5, False, MUTED, MONO)]])
    text(slide, MARGIN, SH - Inches(0.42), CONTENT_W, Inches(0.2),
         [[t(right.upper(), 7.5, False, MUTED, MONO)]], align=PP_ALIGN.RIGHT)


def new_slide(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])   # blank
    bg = box(s, 0, 0, SW, SH, fill=WHITE)
    # send the background rectangle behind everything else
    s.shapes._spTree.remove(bg._element)
    s.shapes._spTree.insert(2, bg._element)
    return s


# ═════════════════════════════ SLIDE 1 ═══════════════════════════════════
def slide1(prs):
    s = new_slide(prs)
    y = Inches(0.95)

    text(s, MARGIN, y, CONTENT_W, Inches(0.22),
         [[t("USE CASE 01  ·  PROOF OF CONCEPT PROPOSAL", 10, True, ACCENT, MONO)]])

    text(s, MARGIN, y + Inches(0.36), Inches(8.6), Inches(1.7),
         [[t("AI-Powered Inventory Intelligence & MRO Optimization",
             40, True, INK, SANS)]], line_spacing=0.92)

    text(s, MARGIN, y + Inches(2.02), Inches(9.6), Inches(0.7),
         [[t("Ma'aden Aluminium's storerooms are full — and its plants still go down "
             "waiting for parts. ", 14, False, INK2, SANS),
           t("Both are true at once, in the same building. ", 14, True, INK, SANS),
           t("The money isn't missing; it is in the wrong parts.", 14, False, INK2, SANS)]],
         line_spacing=1.28)

    # three framing figures
    py = y + Inches(2.85)
    pw = Inches(3.28)
    stats = [
        ("20–40%", ACCENT, "of MRO inventory is excess or obsolete — capital frozen in parts that will never be issued"),
        ("10–15%", WARN,   "of critical parts carry stockout risk at the same time — in the same storeroom"),
        ("3–5×",   INK,    "cost premium when the missing part is bought as an emergency instead of planned"),
    ]
    for i, (val, col, cap) in enumerate(stats):
        x = MARGIN + i * (pw + Inches(0.11))
        box(s, x, py, pw, Inches(1.12), fill=PANEL, line=LINE)
        text(s, x + Inches(0.16), py + Inches(0.13), pw - Inches(0.3), Inches(0.3),
             [[t(val, 17, True, col, MONO)]])
        text(s, x + Inches(0.16), py + Inches(0.46), pw - Inches(0.32), Inches(0.6),
             [[t(cap, 9, False, MUTED, SANS)]], line_spacing=1.2)

    # the chain
    cy = py + Inches(1.42)
    label(s, MARGIN, cy, CONTENT_W, "Scope — one integrated chain · two locations · 600 km apart")
    chain = [
        ("Al Ba'itha mine", "Qassim · standalone", "4.0", "Mt/y bauxite", F1, INK2),
        ("Rail link",       "mine → coast",        "600", "km",            F2, INK2),
        ("Alumina refinery","Ras Al Khair",        "1.8", "Mt/y alumina",  F3, F3),
        ("Smelter",         "Ras Al Khair",        "750", "kt/y primary Al", F4, F4),
        ("Rolling mill",    "Ras Al Khair",        "380", "kt/y flat-rolled", F4, F4),
    ]
    nw = CONTENT_W / 5
    ny = cy + Inches(0.26)
    for i, (name, loc, cap, unit, edge, numcol) in enumerate(chain):
        x = MARGIN + i * nw
        box(s, x, ny, nw, Inches(0.92), fill=PANEL, line=LINE)
        accent_bar(s, x, ny, nw, Pt(2.6), edge)
        text(s, x + Inches(0.13), ny + Inches(0.13), nw - Inches(0.26), Inches(0.2),
             [[t(name, 9.5, True, INK, SANS)]])
        text(s, x + Inches(0.13), ny + Inches(0.32), nw - Inches(0.26), Inches(0.18),
             [[t(loc, 8, False, MUTED, SANS)]])
        text(s, x + Inches(0.13), ny + Inches(0.52), nw - Inches(0.26), Inches(0.32),
             [[t(cap, 13, True, numcol, MONO)],
              [t(unit, 7.5, False, MUTED, MONO)]], line_spacing=1.0)

    # geographic grouping under the strip
    gy = ny + Inches(0.98)
    accent_bar(s, MARGIN, gy, nw * 2 - Inches(0.08), Pt(0.9), LINE2)
    text(s, MARGIN, gy + Inches(0.05), nw * 2 - Inches(0.08), Inches(0.2),
         [[t("CENTRAL ARABIA", 7.5, False, MUTED, MONO)]], align=PP_ALIGN.CENTER)
    accent_bar(s, MARGIN + nw * 2 + Inches(0.08), gy, nw * 3 - Inches(0.08), Pt(0.9), ACCENT)
    text(s, MARGIN + nw * 2 + Inches(0.08), gy + Inches(0.05), nw * 3 - Inches(0.08), Inches(0.2),
         [[t("ONE 20 KM² SITE ON THE GULF COAST — THREE PLANTS, MULTIPLE STOREROOMS",
             7.5, False, ACCENT, MONO)]], align=PP_ALIGN.CENTER)

    foot(s, "MD-404-1000-OE-DG-SOW-0000_ · Rev 0.0", "Phase 0 — for management review")


# ═════════════════════════════ SLIDE 2 ═══════════════════════════════════
def slide2(prs):
    s = new_slide(prs)
    slide_head(s, "02", "A day it goes wrong",
               "One ordinary failure at Ras Al Khair — and what it costs before anyone has done anything wrong")

    top = Inches(1.42)
    lw = Inches(7.05)

    label(s, MARGIN, top, lw, "Rolling mill · one bearing")

    events = [
        ("02:14", F2, "A bearing fails. The mill stops.",
         "Normal wear. Nobody made a mistake here — machines fail.", None),
        ("02:40", F3, "Storeroom checked — not in stock.",
         "400 metres away. It was never stocked. This is the failure.", None),
        ("03:10", F4, "Emergency order raised.",
         "Standard lead time six weeks. Air freight instead.", "→ 3–5× the planned price"),
        ("+3 days", F4, "Part lands. Mill restarts.",
         "Three days of flat-rolled output that will not be recovered.", "→ Downtime dwarfs the part"),
    ]
    ey = top + Inches(0.30)
    row_h = Inches(1.13)
    # spine
    accent_bar(s, MARGIN + Inches(0.72), ey + Inches(0.14), Pt(0.9),
               row_h * (len(events) - 1), LINE2)
    for i, (tm, col, head, sub, cost) in enumerate(events):
        ry = ey + i * row_h
        text(s, MARGIN, ry + Inches(0.02), Inches(0.62), Inches(0.2),
             [[t(tm, 11, True, MUTED, MONO)]], align=PP_ALIGN.RIGHT)
        dot = s.shapes.add_shape(MSO_SHAPE.OVAL, MARGIN + Inches(0.66),
                                 ry + Inches(0.06), Inches(0.13), Inches(0.13))
        dot.shadow.inherit = False
        dot.fill.solid(); dot.fill.fore_color.rgb = col
        dot.line.color.rgb = WHITE; dot.line.width = Pt(1.5)
        text(s, MARGIN + Inches(0.95), ry, lw - Inches(1.0), Inches(0.24),
             [[t(head, 12.5, True, INK, SANS)]])
        text(s, MARGIN + Inches(0.95), ry + Inches(0.26), lw - Inches(1.0), Inches(0.24),
             [[t(sub, 9.5, False, MUTED, SANS)]], line_spacing=1.2)
        if cost:
            text(s, MARGIN + Inches(0.95), ry + Inches(0.62), lw - Inches(1.0), Inches(0.2),
                 [[t(cost, 9.5, True, F4, MONO)]])

    # meanwhile panel
    rx = MARGIN + lw + Inches(0.42)
    rw = CONTENT_W - lw - Inches(0.42)
    my = top + Inches(0.42)
    box(s, rx, my, rw, Inches(2.28), fill=PANEL, line=LINE)
    accent_bar(s, rx, my, Pt(2.6), Inches(2.28), WARN)
    text(s, rx + Inches(0.2), my + Inches(0.16), rw - Inches(0.38), Inches(0.2),
         [[t("MEANWHILE · SAME STOREROOM · THREE AISLES AWAY", 7.5, True, WARN, SANS)]])
    text(s, rx + Inches(0.2), my + Inches(0.42), rw - Inches(0.38), Inches(0.5),
         [[t("400 filter cartridges for a unit removed in 2019", 13, True, INK, SANS)]],
         line_spacing=1.15)
    text(s, rx + Inches(0.2), my + Inches(1.02), rw - Inches(0.38), Inches(0.6),
         [[t("Fully stocked. Perfectly counted. Correctly recorded in SAP. "
             "Not one of them will ever be issued.", 10, False, MUTED, SANS)]],
         line_spacing=1.25)
    text(s, rx + Inches(0.2), my + Inches(1.78), rw - Inches(0.38), Inches(0.36),
         [[t("SAR 300,000", 21, True, WARN, MONO)]])

    box(s, rx, my + Inches(2.44), rw, Inches(0.82), fill=None, line=LINE2)
    text(s, rx + Inches(0.18), my + Inches(2.58), rw - Inches(0.36), Inches(0.6),
         [[t("It is ", 10, False, INK2, SANS),
           t("not a distance problem", 10, True, INK, SANS),
           t(" — the store is 400 m from the mill. It is not a counting problem either; "
             "the stock records were right.", 10, False, INK2, SANS)]], line_spacing=1.25)

    # verdict
    vy = SH - Inches(1.42)
    box(s, MARGIN, vy, CONTENT_W, Inches(0.82), fill=INK)
    text(s, MARGIN, vy + Inches(0.13), CONTENT_W, Inches(0.3),
         [[t("The money to buy that bearing had already been spent.", 14.5, True, WHITE, SANS)]],
         align=PP_ALIGN.CENTER)
    text(s, MARGIN, vy + Inches(0.46), CONTENT_W, Inches(0.24),
         [[t("It was sitting on a shelf, three aisles away, as something else.",
             10.5, False, RGBColor(0xB9, 0xBC, 0xC0), SANS)]], align=PP_ALIGN.CENTER)

    foot(s, "Illustrative incident — the pattern, not a Ma'aden record", "02 / 04")


# ═════════════════════════════ SLIDE 3 ═══════════════════════════════════
def slide3(prs):
    s = new_slide(prs)
    slide_head(s, "03", "What we are going to build",
               "The seven capabilities in the Scope of Work — in order, in plain language, "
               "with the depth we propose for each")

    caps = [
        ("01", "Predict demand", True,
         "How many of this part will we need in six months — from consumption history plus the "
         "maintenance plan. A planned shutdown is a known spike, not a surprise.",
         "Buy at planned prices, not 3–5× emergency"),
        ("02", "Find the dead money", True,
         "Never-issued items · spares for scrapped equipment · the same part under three numbers · "
         "400 held where 40 would do.",
         "The largest one-time cash release"),
        ("03", "Set the right levels", True,
         "Reorder point and safety stock computed per item from its own demand shape, lead time "
         "and criticality — not a number typed in years ago.",
         "Less capital frozen, same service level"),
        ("04", "Catch what is wrong", False,
         "Negative stock · consumption with no work order · missing units of measure · blank "
         "manufacturer part numbers · impossible lead times.",
         "Data trust — everything else depends on it"),
        ("05", "Move it, don't buy it", False,
         "One storeroom holds 40 idle while another is about to buy five. Costed by distance — "
         "across the Ras Al Khair site, or 600 km from the mine.",
         "Free inventory; avoids the purchase entirely"),
        ("06", "Price the trade-off", False,
         "“What if we accept 95% service instead of 98%?” — cash released plotted against "
         "risk accepted, with the items each scenario touches.",
         "Turns a stocking argument into a decision"),
        ("07", "Ask it a question", True,
         "“Which critical spares at the smelter are below reorder point?” — plain language, "
         "over PiLog MDRM and ERP data.",
         "Adoption — no BI training needed"),
    ]
    tags = {"01": ("Deep", True), "02": ("Deep", True), "03": ("Deep", True),
            "04": ("Solid", False), "05": ("Solid", False),
            "06": ("Interactive", None), "07": ("Deep", True)}

    gx, gy = MARGIN, Inches(1.42)
    gap = Inches(0.11)
    cw = (CONTENT_W - 3 * gap) / 4
    ch = Inches(2.06)

    for i, (num, title, deep, desc, value) in enumerate(caps):
        col, row = i % 4, i // 4
        x = gx + col * (cw + gap)
        y = gy + row * (ch + gap)
        box(s, x, y, cw, ch, fill=ACC_SOFT if deep else PANEL,
            line=ACCENT if deep else LINE)
        if deep:
            accent_bar(s, x, y, Pt(2.6), ch, ACCENT)
        text(s, x + Inches(0.15), y + Inches(0.13), Inches(0.4), Inches(0.2),
             [[t(num, 12, True, ACCENT, MONO)]])
        # depth tag, right-aligned in the header row
        tag_txt, filled = tags[num]
        tw = Inches(0.62) if tag_txt != "Interactive" else Inches(0.85)
        tx = x + cw - tw - Inches(0.13)
        if filled:
            box(s, tx, y + Inches(0.12), tw, Inches(0.19), fill=ACCENT)
            tag_col = WHITE
        elif filled is False:
            box(s, tx, y + Inches(0.12), tw, Inches(0.19), fill=TEAL_SOFT, line=TEAL, line_w=0.6)
            tag_col = TEAL
        else:
            box(s, tx, y + Inches(0.12), tw, Inches(0.19), fill=WARN_SOFT, line=WARN, line_w=0.6)
            tag_col = WARN
        text(s, tx, y + Inches(0.145), tw, Inches(0.16),
             [[t(tag_txt.upper(), 6.5, True, tag_col, SANS)]], align=PP_ALIGN.CENTER)

        text(s, x + Inches(0.15), y + Inches(0.38), cw - Inches(0.3), Inches(0.26),
             [[t(title, 12, True, INK, SANS)]])
        text(s, x + Inches(0.15), y + Inches(0.66), cw - Inches(0.3), Inches(0.9),
             [[t(desc, 8.5, False, MUTED, SANS)]], line_spacing=1.28)
        accent_bar(s, x + Inches(0.15), y + ch - Inches(0.52), cw - Inches(0.3), Pt(0.75),
                   ACCENT if deep else LINE)
        text(s, x + Inches(0.15), y + ch - Inches(0.44), cw - Inches(0.3), Inches(0.34),
             [[t(value, 8.5, True, ACCENT, SANS)]], line_spacing=1.2)

    # eighth cell: how they connect
    x = gx + 3 * (cw + gap)
    y = gy + (ch + gap)
    box(s, x, y, cw, ch, fill=None, line=LINE2)
    text(s, x + Inches(0.15), y + Inches(0.13), cw - Inches(0.3), Inches(0.2),
         [[t("→", 12, True, MUTED, MONO)]])
    text(s, x + Inches(0.15), y + Inches(0.38), cw - Inches(0.3), Inches(0.24),
         [[t("How they connect", 11, True, INK, SANS)]])
    text(s, x + Inches(0.15), y + Inches(0.66), cw - Inches(0.3), Inches(0.9),
         [[t("04", 8.5, True, ACCENT, SANS), t(" cleans the data · ", 8.5, False, MUTED, SANS),
           t("01", 8.5, True, ACCENT, SANS), t(" predicts · ", 8.5, False, MUTED, SANS),
           t("03", 8.5, True, ACCENT, SANS), t(" sets policy · ", 8.5, False, MUTED, SANS),
           t("02", 8.5, True, ACCENT, SANS), t(" and ", 8.5, False, MUTED, SANS),
           t("05", 8.5, True, ACCENT, SANS), t(" release the cash · ", 8.5, False, MUTED, SANS),
           t("06", 8.5, True, ACCENT, SANS), t(" prices the trade-off · ", 8.5, False, MUTED, SANS),
           t("07", 8.5, True, ACCENT, SANS), t(" is the front door.", 8.5, False, MUTED, SANS)]],
         line_spacing=1.28)
    accent_bar(s, x + Inches(0.15), y + ch - Inches(0.52), cw - Inches(0.3), Pt(0.75), LINE)
    text(s, x + Inches(0.15), y + ch - Inches(0.44), cw - Inches(0.3), Inches(0.34),
         [[t("Four is the foundation. Seven is how people reach it.", 8.5, True, MUTED, SANS)]],
         line_spacing=1.2)

    # legend + out of scope
    ly = gy + 2 * (ch + gap) + Inches(0.06)
    box(s, MARGIN, ly, Inches(0.16), Inches(0.16), fill=ACC_SOFT, line=ACCENT, line_w=0.6)
    text(s, MARGIN + Inches(0.26), ly - Inches(0.01), Inches(4.2), Inches(0.2),
         [[t("Deep — real algorithms, defensible under expert questioning", 8.5, False, MUTED, SANS)]])
    box(s, MARGIN + Inches(4.6), ly, Inches(0.16), Inches(0.16), fill=PANEL, line=LINE2, line_w=0.6)
    text(s, MARGIN + Inches(4.86), ly - Inches(0.01), Inches(3.4), Inches(0.2),
         [[t("Solid — real logic, narrower scope for a POC", 8.5, False, MUTED, SANS)]])

    ox = MARGIN + Inches(8.3)
    box(s, ox, ly - Inches(0.12), CONTENT_W - Inches(8.3), Inches(0.42), fill=None, line=LINE2)
    text(s, ox + Inches(0.14), ly - Inches(0.03), CONTENT_W - Inches(8.58), Inches(0.3),
         [[t("Out of scope: ", 8.5, True, INK, SANS),
           t("ERP write-back · SSO · automatic POs. ", 8.5, False, INK2, SANS),
           t("It reads and recommends; a human decides.", 8.5, True, INK, SANS)]],
         line_spacing=1.2)

    foot(s, "All seven demonstrated end to end · four built deep", "03 / 04")


# ═════════════════════════════ SLIDE 4 ═══════════════════════════════════
def slide4(prs):
    s = new_slide(prs)
    slide_head(s, "04", "How it is built — and how it reaches your real data",
               "Data flows one way. Nothing on the right computes; nothing in the middle touches your systems")

    cols = [
        ("Sources", 1.0, [
            ("ERP — SAP", "Stock, purchase orders, movements", False),
            ("PiLog MDRM", "Material master, ISO 8000 taxonomy", False),
            ("CMMS / EAM", "Work orders, equipment criticality", False)]),
        ("Ingestion", 0.92, [
            ("Adapter layer", "One interface, any source", True),
            ("Synthetic generator", "Plugs in here for the POC — and is replaced, not rebuilt, for the pilot", False)]),
        ("Intelligence", 1.08, [
            ("Data quality & anomaly engine", "", False),
            ("Demand classifier → forecaster", "Routes each item to the right method", False),
            ("Stocking policy engine", "Reorder point, safety stock", False),
            ("Dead-money & transfer optimiser", "", False)]),
        ("Surface", 1.0, [
            ("Executive dashboard", "Capital at risk, by site", False),
            ("Planner work queue", "Ranked in SAR, not by severity label", False),
            ("Scenario simulator", "", False),
            ("Conversational interface", "Plain-language questions", True)]),
    ]

    arrow_w = Inches(0.34)
    total_flex = sum(c[1] for c in cols)
    avail = CONTENT_W - 3 * arrow_w
    top = Inches(1.42)
    col_h = Inches(3.55)

    x = MARGIN
    for ci, (title, flex, items) in enumerate(cols):
        cw = Emu(int(avail * flex / total_flex))
        label(s, x, top, cw, title)
        accent_bar(s, x, top + Inches(0.22), cw, Pt(0.75), LINE)
        by = top + Inches(0.36)
        for (name, sub, hl) in items:
            bh = Inches(0.72) if sub else Inches(0.46)
            box(s, x, by, cw, bh, fill=ACC_SOFT if hl else PANEL, line=ACCENT if hl else LINE)
            text(s, x + Inches(0.13), by + Inches(0.10), cw - Inches(0.26), Inches(0.24),
                 [[t(name, 10, True, ACCENT if hl else INK, SANS)]], line_spacing=1.15)
            if sub:
                text(s, x + Inches(0.13), by + Inches(0.34), cw - Inches(0.26), Inches(0.34),
                     [[t(sub, 8.5, False, MUTED, SANS)]], line_spacing=1.2)
            by = by + bh + Inches(0.09)
        x = x + cw
        if ci < 3:
            text(s, x, top + Inches(1.5), arrow_w, Inches(0.3),
                 [[t("→", 15, False, LINE2, SANS)]], align=PP_ALIGN.CENTER)
            x = x + arrow_w

    # two design decisions
    cy = top + col_h + Inches(0.28)
    cw2 = (CONTENT_W - Inches(0.16)) / 2
    callouts = [
        ("Design decision 1 — the adapter layer",
         [("“How long before this runs on our real data?”  ", False),
          ("Replace one layer — not rebuild it.", True),
          ("  The POC is built to be promoted to pilot, not thrown away.", False)]),
        ("Design decision 2 — the AI boundary",
         [("The AI narrates. It never computes.", True),
          ("  It calls the engine and reads back the result, always showing the numbers "
           "and the item list behind it.", False)]),
    ]
    for i, (k, parts) in enumerate(callouts):
        x = MARGIN + i * (cw2 + Inches(0.16))
        box(s, x, cy, cw2, Inches(0.95), fill=PANEL, line=LINE)
        accent_bar(s, x, cy, cw2, Pt(2.6), ACCENT)
        text(s, x + Inches(0.16), cy + Inches(0.15), cw2 - Inches(0.32), Inches(0.2),
             [[t(k.upper(), 8, True, ACCENT, SANS)]])
        runs = [(t(p, 10, b, INK if b else INK2, SANS)) for (p, b) in parts]
        text(s, x + Inches(0.16), cy + Inches(0.4), cw2 - Inches(0.32), Inches(0.5),
             [runs], line_spacing=1.28)

    foot(s, "Open dependency: does a CMMS/EAM exist and is it reachable?", "04 / 04")


def main():
    prs = Presentation()
    prs.slide_width, prs.slide_height = SW, SH
    slide1(prs); slide2(prs); slide3(prs); slide4(prs)
    out = "Maaden-MRO-Pitch.pptx"
    prs.save(out)
    print("wrote", out)


if __name__ == "__main__":
    main()
