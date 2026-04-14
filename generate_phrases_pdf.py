"""
Generate a printable A4 PDF reference card for all H and P phrases.
Two sections: English and Italian, each with H phrases then P phrases.
Font: Helvetica Neue (embedded from macOS system font).
"""

import sys
import os

# ── Make the project importable ──────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from data.hazard_phrases import H_EN, H_IT, P_EN, P_IT

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether,
)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER

# ── Register Helvetica Neue ───────────────────────────────────────────────────
TTC = "/System/Library/Fonts/HelveticaNeue.ttc"
pdfmetrics.registerFont(TTFont("HN",       TTC, subfontIndex=0))
pdfmetrics.registerFont(TTFont("HN-Bold",  TTC, subfontIndex=1))

# ── Styles ────────────────────────────────────────────────────────────────────
ACCENT      = colors.HexColor("#1a56a0")   # deep blue for headings / rules
RULE_COLOR  = colors.HexColor("#c8d8f0")   # light blue rule

# Code cell backgrounds
CODE_BG_H   = colors.HexColor("#fdecea")   # soft red  for H phrases
CODE_BG_P   = colors.HexColor("#e8f0fd")   # soft blue for P phrases
CODE_BG_EUH = colors.HexColor("#fff3cd")   # amber     for EUH phrases

# Code text colours (matching the tint)
CODE_FG_H   = colors.HexColor("#b71c1c")   # dark red
CODE_FG_P   = colors.HexColor("#1a56a0")   # dark blue
CODE_FG_EUH = colors.HexColor("#7c4a00")   # dark amber

TEXT_DARK   = colors.HexColor("#1a1a1a")
TEXT_MUTED  = colors.HexColor("#555555")

def make_styles():
    title_style = ParagraphStyle(
        "CoverTitle",
        fontName="HN-Bold",
        fontSize=28,
        leading=34,
        textColor=ACCENT,
        alignment=TA_CENTER,
        spaceAfter=6,
    )
    subtitle_style = ParagraphStyle(
        "CoverSub",
        fontName="HN",
        fontSize=13,
        leading=17,
        textColor=TEXT_MUTED,
        alignment=TA_CENTER,
        spaceAfter=4,
    )
    lang_heading = ParagraphStyle(
        "LangHeading",
        fontName="HN-Bold",
        fontSize=16,
        leading=20,
        textColor=ACCENT,
        spaceBefore=4,
        spaceAfter=2,
    )
    section_heading = ParagraphStyle(
        "SectionHeading",
        fontName="HN-Bold",
        fontSize=11,
        leading=14,
        textColor=TEXT_DARK,
        spaceBefore=10,
        spaceAfter=4,
    )
    code_style = ParagraphStyle(
        "Code",
        fontName="HN-Bold",
        fontSize=8,
        leading=10,
        textColor=ACCENT,
        alignment=TA_LEFT,
    )
    phrase_style = ParagraphStyle(
        "Phrase",
        fontName="HN",
        fontSize=8,
        leading=10.5,
        textColor=TEXT_DARK,
        alignment=TA_LEFT,
    )
    footer_style = ParagraphStyle(
        "Footer",
        fontName="HN",
        fontSize=7,
        textColor=TEXT_MUTED,
        alignment=TA_CENTER,
    )
    return {
        "title": title_style,
        "subtitle": subtitle_style,
        "lang_heading": lang_heading,
        "section_heading": section_heading,
        "code": code_style,
        "phrase": phrase_style,
        "footer": footer_style,
    }


def build_phrase_table(phrases_dict, code_bg, code_fg, styles, euh=False):
    """
    Build a two-column table of (CODE, phrase text) pairs.
    phrases_dict : ordered dict of {code: text}
    code_bg      : background colour for the code cell
    code_fg      : text colour for the code
    euh          : if True, widen code column to fit "EUH066" without wrapping
    """
    col_w    = (A4[0] - 30*mm) / 2   # half usable width
    code_col = 16*mm if euh else 12*mm   # wider for EUH codes

    # Per-entry code style with the right fg colour
    entry_code_style = ParagraphStyle(
        "EntryCode",
        parent=styles["code"],
        textColor=code_fg,
    )

    rows = []
    items = list(phrases_dict.items())
    mid   = (len(items) + 1) // 2
    left  = items[:mid]
    right = items[mid:]

    max_rows = max(len(left), len(right))
    for i in range(max_rows):
        row = []
        for side in (left, right):
            if i < len(side):
                code, text = side[i]
                code_p   = Paragraph(code, entry_code_style)
                phrase_p = Paragraph(text, styles["phrase"])
                inner = Table(
                    [[code_p, phrase_p]],
                    colWidths=[code_col, col_w - code_col - 4*mm],
                    style=TableStyle([
                        ("VALIGN",        (0,0), (-1,-1), "TOP"),
                        ("LEFTPADDING",   (0,0), (-1,-1), 3),
                        ("RIGHTPADDING",  (0,0), (-1,-1), 3),
                        ("TOPPADDING",    (0,0), (-1,-1), 2),
                        ("BOTTOMPADDING", (0,0), (-1,-1), 2),
                        ("BACKGROUND",    (0,0), (0,0), code_bg),
                    ])
                )
                row.append(inner)
            else:
                row.append("")

        rows.append(row)

    if not rows:
        return None

    tbl = Table(rows, colWidths=[col_w, col_w],
                style=TableStyle([
                    ("VALIGN",        (0,0), (-1,-1), "TOP"),
                    ("LEFTPADDING",   (0,0), (-1,-1), 0),
                    ("RIGHTPADDING",  (0,0), (-1,-1), 4*mm),
                    ("TOPPADDING",    (0,0), (-1,-1), 0),
                    ("BOTTOMPADDING", (0,0), (-1,-1), 0),
                    ("LINEBELOW",     (0,0), (-1,-2),
                     0.3, colors.HexColor("#e0e8f8")),
                ]))
    return tbl


def build_section(lang_label, H, P, styles):
    """Return a list of flowables for one language section."""
    story = []

    # ── Language page header ──────────────────────────────────────────────
    story.append(Paragraph(lang_label, styles["lang_heading"]))
    story.append(HRFlowable(width="100%", thickness=1.5,
                            color=ACCENT, spaceAfter=8))

    # ── H phrases ────────────────────────────────────────────────────────
    # Separate standard H from EUH
    h_std  = {k: v for k, v in H.items() if not k.startswith("EUH")}
    h_euh  = {k: v for k, v in H.items() if k.startswith("EUH")}

    story.append(Paragraph("H Phrases — Hazard Statements", styles["section_heading"]))
    tbl = build_phrase_table(h_std, CODE_BG_H, CODE_FG_H, styles, euh=False)
    if tbl:
        story.append(tbl)

    if h_euh:
        story.append(Spacer(1, 4*mm))
        story.append(Paragraph("EUH Phrases — Supplemental Hazard Statements",
                                styles["section_heading"]))
        tbl_euh = build_phrase_table(h_euh, CODE_BG_EUH, CODE_FG_EUH, styles, euh=True)
        if tbl_euh:
            story.append(tbl_euh)

    # ── P phrases ────────────────────────────────────────────────────────
    story.append(Spacer(1, 6*mm))
    story.append(HRFlowable(width="100%", thickness=0.5,
                             color=RULE_COLOR, spaceAfter=0))
    story.append(Paragraph("P Phrases — Precautionary Statements",
                             styles["section_heading"]))
    tbl_p = build_phrase_table(P, CODE_BG_P, CODE_FG_P, styles, euh=False)
    if tbl_p:
        story.append(tbl_p)

    return story


def on_page(canvas, doc):
    """Draw page number footer on every page except the cover."""
    if doc.page == 1:
        return
    canvas.saveState()
    canvas.setFont("HN", 7)
    canvas.setFillColor(TEXT_MUTED)
    w, h = A4
    canvas.drawCentredString(w/2, 10*mm,
        f"H & P Phrases — CLP/GHS Reference  ·  Page {doc.page}")
    canvas.restoreState()


def generate(out_path: str):
    styles = make_styles()

    doc = SimpleDocTemplate(
        out_path,
        pagesize=A4,
        leftMargin=15*mm,
        rightMargin=15*mm,
        topMargin=15*mm,
        bottomMargin=18*mm,
        title="H & P Phrases — CLP/GHS Reference",
        author="CompouNdex",
        subject="CLP/GHS Hazard and Precautionary Statements EN/IT",
    )

    story = []

    # ── Cover ─────────────────────────────────────────────────────────────
    story.append(Spacer(1, 30*mm))
    story.append(Paragraph("H &amp; P Phrases", styles["title"]))
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph("CLP / GHS Reference", styles["subtitle"]))
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph("English · Italiano", styles["subtitle"]))
    story.append(Spacer(1, 8*mm))
    story.append(HRFlowable(width="60%", thickness=1, color=ACCENT,
                             hAlign="CENTER"))
    story.append(Spacer(1, 6*mm))
    story.append(Paragraph(
        "Regulation (EC) No 1272/2008 (CLP) and subsequent amendments",
        styles["footer"],
    ))
    story.append(Paragraph(
        "Regolamento (CE) n. 1272/2008 (CLP) e successive modifiche",
        styles["footer"],
    ))

    story.append(PageBreak())

    # ── English section ───────────────────────────────────────────────────
    story += build_section("English", H_EN, P_EN, styles)

    story.append(PageBreak())

    # ── Italian section ───────────────────────────────────────────────────
    story += build_section("Italiano", H_IT, P_IT, styles)

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    print(f"✓ PDF written to: {out_path}")


if __name__ == "__main__":
    out = os.path.join(BASE_DIR, "static", "guidelines", "HP_phrases_reference.pdf")
    generate(out)
