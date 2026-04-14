"""
Generate 9 printable A4 lab signs — English + Italian.
One page per sign, all collected in one PDF.
Font: Helvetica Neue.

Color legend:
  Red   stripe  =  prohibition / do-not rule
  Orange stripe =  required action / must-do
  Blue  stripe  =  informational / organisational
"""
import os, sys
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import simpleSplit

# ── Fonts ─────────────────────────────────────────────────────────────────────
TTC = "/System/Library/Fonts/HelveticaNeue.ttc"
pdfmetrics.registerFont(TTFont("HN",        TTC, subfontIndex=0))
pdfmetrics.registerFont(TTFont("HN-Bold",   TTC, subfontIndex=1))
pdfmetrics.registerFont(TTFont("HN-Italic", TTC, subfontIndex=2))

W, H = A4

def hc(h): return colors.HexColor(h)

def lighten(hex_col, t=0.30):
    c = hc(hex_col)
    return colors.Color(
        c.red   + (1 - c.red)   * t,
        c.green + (1 - c.green) * t,
        c.blue  + (1 - c.blue)  * t,
    )

# ── Rule-kind palette ─────────────────────────────────────────────────────────
KIND = {
    "warn":   {"bg": hc("#C62828"), "label": "X"},   # red   — prohibition
    "action": {"bg": hc("#E65100"), "label": "!"},   # orange— must-do
    "info":   {"bg": hc("#1565C0"), "label": ">"},   # blue  — information
}

# ── Sign data ─────────────────────────────────────────────────────────────────
SIGNS = [
    {
        "n": 1, "name": "OVEN 1",
        "sub_en": "Analytical Oven", "sub_it": "Forno Analitico",
        "bg": "#00695C",
        "rules": [
            {"kind": "warn",
             "en":  "Only analytical glassware",
             "en2": "Remove any markings with acetone or ethanol",
             "it":  "Solo vetreria analitica",
             "it2": "Rimuovere ogni segno con acetone o etanolo"},
            {"kind": "info",
             "en":  "Upper shelf: EPR cells and vials only",
             "it":  "Ripiano superiore: solo celle EPR e vials"},
            {"kind": "action",
             "en":  "Empty this oven every morning",
             "it":  "Svuotare il forno ogni mattina"},
        ],
    },
    {
        "n": 2, "name": "OVEN 2",
        "sub_en": "Synthetic Oven", "sub_it": "Forno da Sintesi",
        "bg": "#BF360C",
        "rules": [
            {"kind": "warn",
             "en":  "Upper shelf for synthesis only — label every item with your name",
             "en2": "Unlabelled glassware will be discarded",
             "it":  "Ripiano superiore solo per la sintesi — etichettare tutto con il proprio nome",
             "it2": "La vetreria senza etichetta verrà eliminata"},
            {"kind": "info",
             "en":  "Bottom shelf: drying synthetic glassware",
             "en2": "Remove any markings with acetone or ethanol",
             "it":  "Ripiano inferiore: asciugatura della vetreria da sintesi",
             "it2": "Rimuovere ogni segno con acetone o etanolo"},
            {"kind": "action",
             "en":  "Empty this oven every morning",
             "it":  "Svuotare il forno ogni mattina"},
        ],
    },
    {
        "n": 3, "name": "SINK",
        "sub_en": "Washing Area", "sub_it": "Area di Lavaggio",
        "bg": "#1565C0",
        "rules": [
            {"kind": "warn",
             "en":  "Do NOT leave anything in the sink",
             "en2": "Wash it immediately!",
             "it":  "NON lasciare nulla nel lavandino",
             "it2": "Lavarlo immediatamente!"},
            {"kind": "info",
             "en":  "If you plan to wash it later, put it on your bench mat",
             "it":  "Se hai intenzione di lavarlo dopo, mettilo sulla tua tovaglietta"},
            {"kind": "action",
             "en":  "Keep the sponge outside the sink",
             "it":  "Tenere la spugna fuori dal lavandino"},
        ],
    },
    {
        "n": 3, "name": "SINK",
        "sub_en": "Washing Area", "sub_it": "Area di Lavaggio",
        "bg": "#1565C0",
        "rules": [
            {"kind": "warn",
             "en":  "Do NOT leave anything in the sink",
             "en2": "Wash it immediately!",
             "it":  "NON lasciare nulla nel lavandino",
             "it2": "Lavarlo immediatamente!"},
            {"kind": "info",
             "en":  "If you plan to wash it later, put it on your bench mat",
             "it":  "Se hai intenzione di lavarlo dopo, mettilo sulla tua tovaglietta"},
            {"kind": "action",
             "en":  "Keep the sponge outside the sink",
             "it":  "Tenere la spugna fuori dal lavandino"},
        ],
    },
    {
        "n": 4, "name": "BALANCE",
        "sub_en": "Analytical Balance", "sub_it": "Bilancia Analitica",
        "bg": "#4527A0",
        "rules": [
            {"kind": "action",
             "en":  "Clean everything after use",
             "en2": "Pay attention to the calibration handle",
             "it":  "Lasciare tutto pulito dopo l'uso",
             "it2": "Prestare attenzione alla maniglia di calibrazione"},
            {"kind": "warn",
             "en":  "Do not leave spatulas, glassware or reagents here",
             "it":  "Non lasciare qui spatole, vetreria o reagenti"},
        ],
    },
    {
        "n": 5, "name": "HOOD 1",
        "sub_en": "Fume Hood", "sub_it": "Cappa Aspirante",
        "bg": "#2E7D32",
        "rules": [
            {"kind": "warn",
             "en":  "Do not store reagents or samples here",
             "it":  "Non conservare qui reagenti o campioni"},
            {"kind": "action",
             "en":  "Clean after use",
             "it":  "Pulire dopo l'uso"},
        ],
    },
    {
        "n": 6, "name": "HOOD 2",
        "sub_en": "Fume Hood", "sub_it": "Cappa Aspirante",
        "bg": "#B71C1C",
        "rules": [
            {"kind": "warn",
             "en":  "Do not store reagents or samples here",
             "it":  "Non conservare qui reagenti o campioni"},
            {"kind": "action",
             "en":  "Clean after use",
             "it":  "Pulire dopo l'uso"},
            {"kind": "warn",
             "en":  "Do not use strong acids or corrosive liquids in this hood",
             "it":  "Non usare acidi forti o liquidi corrosivi in questa cappa"},
        ],
    },
    {
        "n": 7, "name": "WINDOWSILLS",
        "sub_en": "Keep Clear", "sub_it": "Tenere Libero",
        "bg": "#E65100",
        "rules": [
            {"kind": "warn",
             "en":  "Do not leave anything on the windowsills",
             "it":  "Non lasciare nulla sui davanzali"},
        ],
    },
    {
        "n": 8, "name": "GLASSWARE RACK",
        "sub_en": "Storage Rack", "sub_it": "Portavetreria",
        "bg": "#01579B",
        "rules": [
            {"kind": "warn",
             "en":  "Synthetic glassware only",
             "it":  "Solo vetreria da sintesi"},
        ],
    },
    {
        "n": 9, "name": "ANALYTICAL CABINET",
        "sub_en": "Storage Cabinet", "sub_it": "Armadio Analitica",
        "bg": "#283593",
        "rules": [
            {"kind": "warn",
             "en":  "Analytical glassware only",
             "it":  "Solo vetreria analitica"},
            {"kind": "warn",
             "en":  "Do not use volumetric flasks to store reagents",
             "it":  "Non usare i matracci volumetrici per conservare i reagenti"},
        ],
    },
]

# ── Layout constants ──────────────────────────────────────────────────────────
MARGIN    = 13 * mm
STRIPE_W  = 11 * mm      # colored left stripe per rule
GAP_STRIPE = 5 * mm      # gap between stripe and text
RULE_PAD  = 10           # top+bottom padding (pts) inside each rule block
GAP_EN_IT = 6            # pts between EN block and IT block
DIV_GAP   = 12           # pts between rules (for divider line + breathing room)
FOOTER_H  = 7 * mm

EN_FS,  EN_LEAD  = 15, 20
EN2_FS, EN2_LEAD = 11, 15
IT_FS,  IT_LEAD  = 12, 16
IT2_FS, IT2_LEAD = 10, 13

TEXT_X = MARGIN + STRIPE_W + GAP_STRIPE
TEXT_W = W - TEXT_X - MARGIN


# ── Helpers ───────────────────────────────────────────────────────────────────

def rule_height(rule):
    """Total pixel height of a rule block (padding included, divider excluded)."""
    en_h   = len(simpleSplit(rule["en"],  "HN-Bold",   EN_FS,  TEXT_W)) * EN_LEAD
    en2_h  = (len(simpleSplit(rule["en2"],"HN",        EN2_FS, TEXT_W)) * EN2_LEAD + 3
              if rule.get("en2") else 0)
    it_h   = len(simpleSplit(rule["it"],  "HN-Italic", IT_FS,  TEXT_W)) * IT_LEAD
    it2_h  = (len(simpleSplit(rule["it2"],"HN-Italic", IT2_FS, TEXT_W)) * IT2_LEAD + 3
              if rule.get("it2") else 0)
    return RULE_PAD + en_h + en2_h + GAP_EN_IT + it_h + it2_h + RULE_PAD


def draw_sign(c, sign):
    bg = hc(sign["bg"])

    # ── Full-page light background ────────────────────────────────────────────
    c.setFillColor(hc("#F5F5F5"))
    c.rect(0, 0, W, H, fill=1, stroke=0)

    # ── Header block ─────────────────────────────────────────────────────────
    HEADER_H = H * 0.40
    c.setFillColor(bg)
    c.rect(0, H - HEADER_H, W, HEADER_H, fill=1, stroke=0)

    # Subtle diagonal stripe overlay for depth
    c.saveState()
    c.setFillColor(lighten(sign["bg"], 0.10))
    c.rect(0, H - HEADER_H, W * 0.45, HEADER_H, fill=1, stroke=0)
    c.restoreState()
    # Re-draw darker right portion for even look
    c.setFillColor(lighten(sign["bg"], 0.05))
    c.rect(W * 0.45, H - HEADER_H, W * 0.55, HEADER_H, fill=1, stroke=0)
    # Re-draw a clean top strip
    c.setFillColor(bg)
    c.rect(0, H - HEADER_H, W, HEADER_H * 0.08, fill=1, stroke=0)

    # Sign number — top-right corner, white rounded box
    NUM_W, NUM_H = 16 * mm, 11 * mm
    nx = W - MARGIN - NUM_W
    ny = H - MARGIN - NUM_H
    c.setFillColor(lighten(sign["bg"], 0.35))
    c.roundRect(nx, ny, NUM_W, NUM_H, 3*mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("HN-Bold", 13)
    c.drawCentredString(nx + NUM_W/2, ny + 3.2, f"#{sign['n']}")

    # Equipment name — large, centered, white
    name_fs = 38
    while c.stringWidth(sign["name"], "HN-Bold", name_fs) > W - 3*MARGIN and name_fs > 20:
        name_fs -= 1
    c.setFillColor(colors.white)
    c.setFont("HN-Bold", name_fs)
    name_y = H - HEADER_H + HEADER_H * 0.50 + name_fs * 0.18
    c.drawCentredString(W / 2, name_y, sign["name"])

    # Subtitle: EN · IT — smaller, slightly transparent white
    sub = f"{sign['sub_en']}  ·  {sign['sub_it']}"
    sub_fs = 12.5
    while c.stringWidth(sub, "HN", sub_fs) > W - 2.5 * MARGIN and sub_fs > 8.5:
        sub_fs -= 0.5
    c.setFillColor(lighten(sign["bg"], 0.70))
    c.setFont("HN", sub_fs)
    sub_y = H - HEADER_H + HEADER_H * 0.24
    c.drawCentredString(W / 2, sub_y, sub)

    # ── Footer strip ─────────────────────────────────────────────────────────
    c.setFillColor(bg)
    c.rect(0, 0, W, FOOTER_H, fill=1, stroke=0)

    # ── Rules section ────────────────────────────────────────────────────────
    CONTENT_TOP = H - HEADER_H - 8 * mm
    CONTENT_BOT = FOOTER_H + 8 * mm
    avail_h = CONTENT_TOP - CONTENT_BOT

    heights = [rule_height(r) for r in sign["rules"]]
    n_div   = len(sign["rules"]) - 1
    total_h = sum(heights) + n_div * DIV_GAP

    # Vertically center the rule block
    start_y = CONTENT_TOP - (avail_h - total_h) / 2
    start_y = min(start_y, CONTENT_TOP)   # clamp to top

    y = start_y

    for i, (rule, rh) in enumerate(zip(sign["rules"], heights)):
        # Divider between rules
        if i > 0:
            mid_y = y - DIV_GAP / 2
            c.setStrokeColor(hc("#D0D0D0"))
            c.setLineWidth(0.4)
            c.line(MARGIN + STRIPE_W + 3*mm, mid_y, W - MARGIN, mid_y)
            y -= DIV_GAP

        rule_top = y
        rule_bot = y - rh

        # ── Colored left stripe ───────────────────────────────────────────────
        stripe_bg = KIND[rule["kind"]]["bg"]
        c.setFillColor(stripe_bg)
        c.rect(MARGIN, rule_bot, STRIPE_W, rh, fill=1, stroke=0)

        # Stripe label (X / ! / >)
        c.setFillColor(colors.white)
        c.setFont("HN-Bold", 13)
        c.drawCentredString(MARGIN + STRIPE_W / 2, rule_bot + rh / 2 - 4.5,
                            KIND[rule["kind"]]["label"])

        # ── Text block ───────────────────────────────────────────────────────
        # Start baseline: top of rule minus padding minus first-line ascent
        ty = rule_top - RULE_PAD - EN_FS + 4

        # EN — bold, dark
        c.setFillColor(hc("#1A1A1A"))
        c.setFont("HN-Bold", EN_FS)
        for line in simpleSplit(rule["en"], "HN-Bold", EN_FS, TEXT_W):
            c.drawString(TEXT_X, ty, line)
            ty -= EN_LEAD

        # EN2 — regular, muted (sub-detail)
        if rule.get("en2"):
            ty -= 3
            c.setFillColor(hc("#555555"))
            c.setFont("HN", EN2_FS)
            for line in simpleSplit(rule["en2"], "HN", EN2_FS, TEXT_W):
                c.drawString(TEXT_X, ty, line)
                ty -= EN2_LEAD

        ty -= GAP_EN_IT

        # IT — italic, medium dark
        c.setFillColor(hc("#3A3A3A"))
        c.setFont("HN-Italic", IT_FS)
        for line in simpleSplit(rule["it"], "HN-Italic", IT_FS, TEXT_W):
            c.drawString(TEXT_X, ty, line)
            ty -= IT_LEAD

        # IT2 — italic small, lighter
        if rule.get("it2"):
            ty -= 3
            c.setFillColor(hc("#666666"))
            c.setFont("HN-Italic", IT2_FS)
            for line in simpleSplit(rule["it2"], "HN-Italic", IT2_FS, TEXT_W):
                c.drawString(TEXT_X, ty, line)
                ty -= IT2_LEAD

        y = rule_bot

    # ── Legend (bottom of content area) ──────────────────────────────────────
    legend_y = CONTENT_BOT - 5
    c.setFont("HN", 6.5)
    legend_items = [
        (KIND["warn"]["bg"],   "X  Prohibition"),
        (KIND["action"]["bg"], "!  Required action"),
        (KIND["info"]["bg"],   ">  Information"),
    ]
    lx = MARGIN + STRIPE_W + GAP_STRIPE
    for k_bg, k_label in legend_items:
        c.setFillColor(k_bg)
        c.rect(lx, legend_y + 1, 5, 5, fill=1, stroke=0)
        c.setFillColor(hc("#777777"))
        c.drawString(lx + 7, legend_y + 1, k_label)
        lx += 45

    c.showPage()


# ── Entry point ───────────────────────────────────────────────────────────────

def generate(out_path):
    c = rl_canvas.Canvas(out_path, pagesize=A4)
    c.setTitle("Lab Signs — CompouNdex")
    for sign in SIGNS:
        draw_sign(c, sign)
    c.save()
    print(f"✓  {len(SIGNS)} signs written to: {out_path}")


if __name__ == "__main__":
    BASE = os.path.dirname(os.path.abspath(__file__))
    out  = os.path.join(BASE, "static", "guidelines", "lab_signs.pdf")
    generate(out)
