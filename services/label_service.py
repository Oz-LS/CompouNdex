"""
Label PDF generation service — Phase 6.

Generates an A4 PDF with CLP-compliant labels packed row-by-row.

Layout (6 rows separated by solid lines):
  1. Substance name
  2. CAS  ·  EC number
  3. Molecular formula  ·  Molar mass  ·  Nominal quantity
  4. Purity / Concentration / Density   (row omitted when all absent)
  5. Pictograms (left column) | Signal word + H phrases + P phrases (right)
  6. Handwrite field  "Opened on…"  or  "Prepared by… on…"

Five predefined formats (width × height in mm):
  1kg  → 105 × 148    500g → 105 × 105
  100g →  74 ×  74     20g →  52 ×  74    1g → 38 × 52

Formats 20g and 1g suppress phrase text (codes only).

Pictograms: PNG files in static/pictograms/GHS01.png … GHS09.png are used
when available. If a PNG is missing, a simple vector diamond with a symbol
letter is drawn as fallback.
"""
from __future__ import annotations
import io
import os

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfgen.canvas import Canvas

# ── Format table ──────────────────────────────────────────────────────────────
FORMATS: dict[str, dict] = {
    "1kg":  {"w": 105*mm, "h": 148*mm, "fb": 7.5, "fn": 9.5, "fs": 9.0,
             "pic": 18*mm, "show_text": False},
    "500g": {"w": 105*mm, "h": 105*mm, "fb": 7.0, "fn": 9.0, "fs": 8.0,
             "pic": 18*mm, "show_text": False},
    "100g": {"w":  74*mm, "h":  74*mm, "fb": 6.5, "fn": 8.5, "fs": 7.5,
             "pic": 14*mm, "show_text": False},
    "20g":  {"w":  52*mm, "h":  74*mm, "fb": 5.5, "fn": 7.0, "fs": 6.5,
             "pic": 11*mm, "show_text": False},
    "1g":   {"w":  38*mm, "h":  52*mm, "fb": 5.0, "fn": 6.0, "fs": 6.0,
             "pic":  4*mm, "show_text": False},
}

BORDER_W = 1.2   # pt — outer border
LINE_W   = 0.8   # pt — internal dividers
PAD      = 1.8 * mm   # horizontal padding

A4_W, A4_H = A4
MARGIN = 8 * mm

# Colours
BLACK = colors.black
RED   = colors.HexColor("#cc0000")
WARN  = colors.HexColor("#c65000")
GREY  = colors.HexColor("#555555")
DASH  = colors.HexColor("#aaaaaa")
CREAM = colors.HexColor("#fffdf5")

# GHS fallback symbols (single char, drawn in red if no PNG is found)
GHS_FALLBACK: dict[str, str] = {
    "GHS01": "X",   # Explosive
    "GHS02": "F",   # Flammable
    "GHS03": "O",   # Oxidizing
    "GHS04": "G",   # Compressed gas
    "GHS05": "C",   # Corrosive
    "GHS06": "T",   # Toxic (skull)
    "GHS07": "!",   # Harmful
    "GHS08": "H",   # Health hazard
    "GHS09": "E",   # Environmental
}


# ── Public API ────────────────────────────────────────────────────────────────

def generate_pdf(cart: list[dict], reagents_by_id: dict[int, dict],
                 static_folder: str | None = None,
                 mixtures_by_id: dict[int, dict] | None = None) -> bytes:
    """
    Render all cart entries to an A4 PDF and return the bytes.

    cart entries (from session):
        reagent_id or mixture_id, display_name, cas_number, format_size, copies,
        is_prepared, qty_display, purity_display

    reagents_by_id:  reagent_id → full reagent dict (from reagent_service)
    mixtures_by_id:  mixture_id → mixture dict (from mixture_service)
    static_folder:   path to Flask static/ for PNG lookup; may be None
    """
    buf = io.BytesIO()
    c   = Canvas(buf, pagesize=A4)

    # Expand copies
    jobs: list[tuple[dict, dict, str]] = []
    for entry in cart:
        mid    = entry.get("mixture_id")
        rid    = entry.get("reagent_id")
        fmt    = entry.get("format_size", "100g")
        copies = max(1, int(entry.get("copies", 1)))
        if mid:
            rdata = (mixtures_by_id or {}).get(mid)
        else:
            rdata = reagents_by_id.get(rid)
        if rdata is None:
            continue
        for _ in range(copies):
            jobs.append((entry, rdata, fmt))

    # Pack onto A4 pages, left-to-right then top-to-bottom
    page_usable_w = A4_W - 2 * MARGIN
    x     = MARGIN
    y     = A4_H - MARGIN
    row_h = 0.0

    for entry, rdata, fmt in jobs:
        spec = FORMATS.get(fmt, FORMATS["100g"])
        lw, lh = spec["w"], spec["h"]

        # New row when label doesn't fit horizontally
        if x + lw > MARGIN + page_usable_w + 0.5:
            x  = MARGIN
            y -= row_h + 2 * mm
            row_h = 0.0

        # New page when label doesn't fit vertically
        if y - lh < MARGIN - 0.5:
            c.showPage()
            x, y  = MARGIN, A4_H - MARGIN
            row_h = 0.0

        _draw_label(c, x, y - lh, lw, lh, spec, rdata, entry, static_folder)
        x    += lw + 1.5 * mm
        row_h = max(row_h, lh)

    c.save()
    buf.seek(0)
    return buf.read()


# ── Label renderer ────────────────────────────────────────────────────────────

def _draw_label(c: Canvas, ox: float, oy: float, w: float, h: float,
                spec: dict, r: dict, entry: dict,
                static_folder: str | None) -> None:
    """
    Draw one label. (ox, oy) is the bottom-left corner in ReportLab coords.
    All internal measurements work top-down from (ox, oy+h).
    """
    fb = spec["fb"]
    fn = spec["fn"]
    fs = spec["fs"]
    pic_size  = spec["pic"]
    show_text = spec["show_text"]

    pt = lambda pts: pts * 0.352778 * mm   # pt → mm in user space

    # Outer border
    c.setStrokeColor(BLACK)
    c.setLineWidth(BORDER_W)
    c.rect(ox, oy, w, h)

    # ── Row heights (all proportional to font size) ───────────────────────
    rh_name  = pt(fn) + 3.0 * mm
    rh_ids   = pt(fb) + 2.5 * mm
    rh_props = pt(fb) + 2.5 * mm

    def hline(y):
        c.setLineWidth(LINE_W)
        c.setStrokeColor(BLACK)
        c.line(ox, y, ox + w, y)

    def draw_text(tx, ty, text: str, size: float,
                  bold=False, mono=False, color=BLACK):
        font = ("Helvetica-Bold" if bold else
                "Courier" if mono else "Helvetica")
        c.setFont(font, size)
        c.setFillColor(color)
        avail = w - 2 * PAD
        while len(text) > 3 and c.stringWidth(text, font, size) > avail:
            text = text[:-2] + "…"
        c.drawString(tx, ty, text)

    # cursor: start from top
    cur_top = oy + h

    # ── Row 1: Name ───────────────────────────────────────────────────────
    r1_top = cur_top
    r1_bot = r1_top - rh_name
    hline(r1_bot)
    text_y = r1_bot + (rh_name - pt(fn)) / 2
    draw_text(ox + PAD, text_y, r.get("display_name", ""), fn, bold=True)
    cur_top = r1_bot

    if r.get("is_mixture"):
        # ── Special solution: composition block (replaces CAS + formula rows) ──
        comps    = r.get("components") or []
        solvents = r.get("solvents") or []

        # Build composition lines: "Name (Formula) concentration" per compound
        comp_lines = []
        for comp in comps:
            name    = comp.get("name") or ""
            formula = comp.get("molecular_formula") or ""
            conc    = comp.get("concentration_mM")
            if conc is not None:
                line = f"{name} ({formula}) {conc:.1f} mM" if formula else f"{name} {conc:.1f} mM"
            else:
                amt  = comp.get("amount", "")
                unit = comp.get("amount_unit", "")
                line = f"{name} ({formula}) {amt} {unit}" if formula else f"{name} {amt} {unit}"
            comp_lines.append(line.strip())

        # Solvent suffix: "in Water" or "in Water / Ethanol"
        solvent_names = [s.get("name", "") for s in solvents if s.get("name")]
        solvent_text  = "in " + " / ".join(solvent_names) if solvent_names else ""

        # Adaptive font to fit all lines
        n_lines = len(comp_lines) + (1 if solvent_text else 0)
        comp_fs = fb
        avail   = w - 2 * PAD
        line_h  = pt(comp_fs) + 1.0 * mm
        comp_block_h = max(n_lines * line_h + 2 * mm, rh_ids + rh_props)

        # Shrink font if lines don't fit or are too wide
        while comp_fs > 3.5:
            line_h = pt(comp_fs) + 1.0 * mm
            fits_h = n_lines * line_h + 2 * mm <= comp_block_h
            widths_ok = all(c.stringWidth(ln, "Helvetica", comp_fs) <= avail for ln in comp_lines)
            if fits_h and widths_ok:
                break
            comp_fs -= 0.5
        line_h = pt(comp_fs) + 1.0 * mm

        comp_bot = cur_top - comp_block_h
        hline(comp_bot)

        py = cur_top - pt(comp_fs) - 1.5 * mm
        c.setFont("Helvetica", comp_fs)
        c.setFillColor(BLACK)
        for ln in comp_lines:
            # Truncate if still too wide
            disp = ln
            while len(disp) > 3 and c.stringWidth(disp, "Helvetica", comp_fs) > avail:
                disp = disp[:-2] + "…"
            c.drawString(ox + PAD, py, disp)
            py -= line_h
        if solvent_text:
            c.setFont("Helvetica-Oblique", comp_fs)
            c.setFillColor(GREY)
            disp = solvent_text
            while len(disp) > 3 and c.stringWidth(disp, "Helvetica-Oblique", comp_fs) > avail:
                disp = disp[:-2] + "…"
            c.drawString(ox + PAD, py, disp)

        cur_top = comp_bot
    else:
        # ── Row 2: CAS · EC ──────────────────────────────────────────────
        r2_bot = cur_top - rh_ids
        hline(r2_bot)
        cas = r.get("cas_number", "")
        ec  = r.get("ec_number", "")
        ids = f"CAS {cas}" + (f"   ·   EC {ec}" if ec else "")
        text_y = r2_bot + (rh_ids - pt(fb)) / 2
        draw_text(ox + PAD, text_y, ids, fb, mono=True)
        cur_top = r2_bot

        # ── Row 3: Formula · MW · Quantity ────────────────────────────────
        r3_bot = cur_top - rh_props
        hline(r3_bot)
        qty_disp = entry.get("qty_display", "")
        formula = (r.get("molecular_formula_classic")
                   or r.get("molecular_formula", ""))
        mw       = r.get("molecular_weight")
        parts = [p for p in [
            formula,
            f"{mw} g/mol" if mw else "",
            qty_disp,
        ] if p]
        row3_text = "  ·  ".join(parts)
        text_y = r3_bot + (rh_props - pt(fb)) / 2
        draw_text(ox + PAD, text_y, row3_text, fb)
        cur_top = r3_bot

    # ── Row 4: Purity (optional) ───────────────────────────────────────
    purity_disp = entry.get("purity_display", "")
    sec_parts   = []
    if purity_disp and purity_disp not in ("", "—", "-"):
        sec_parts.append(f"Purity: {purity_disp}")
    if sec_parts:
        r4_bot = cur_top - rh_props
        hline(r4_bot)
        text_y = r4_bot + (rh_props - pt(fb)) / 2
        draw_text(ox + PAD, text_y, "   ".join(sec_parts), fb)
        cur_top = r4_bot

    # ── Row 6 (bottom): Handwrite field — bigger box ─────────────────────
    hw_h   = rh_props * 3.2
    hw_bot = oy
    hw_top = oy + hw_h

    is_prep = entry.get("is_prepared", False)
    pad_hw = 1.5 * mm
    avail_hw = w - 4 * pad_hw

    c.setFillColor(CREAM)
    c.setStrokeColor(DASH)
    c.setLineWidth(0.6)
    c.setDash(2, 2)
    c.roundRect(ox + pad_hw, hw_bot + pad_hw,
                w - 2 * pad_hw, hw_h - 2 * pad_hw,
                1.5 * mm, stroke=1, fill=1)
    c.setDash()

    # Adaptive font for handwrite text — shrink to fit width, min 3.5pt
    hw_fs = fb - 0.5
    if is_prep:
        # Two lines: "Prepared by: ________" and "on: ___ / ___ / ______"
        hw_line1 = "Prepared by: ________________"
        hw_line2 = "on: ___ / ___ / ______"
        while hw_fs > 3.5 and c.stringWidth(hw_line1, "Helvetica-Oblique", hw_fs) > avail_hw:
            hw_fs -= 0.5
        line_sp = pt(hw_fs) + 1.5 * mm
        y_mid   = hw_bot + hw_h / 2
        c.setFont("Helvetica-Oblique", hw_fs)
        c.setFillColor(DASH)
        c.drawString(ox + 2 * pad_hw, y_mid + 0.5 * mm, hw_line1)
        c.drawString(ox + 2 * pad_hw, y_mid - line_sp + 0.5 * mm, hw_line2)
    else:
        hw_text = "Opened on: ___ / ___ / ______"
        while hw_fs > 3.5 and c.stringWidth(hw_text, "Helvetica-Oblique", hw_fs) > avail_hw:
            hw_fs -= 0.5
        c.setFont("Helvetica-Oblique", hw_fs)
        c.setFillColor(DASH)
        c.drawString(ox + 2 * pad_hw,
                     hw_bot + hw_h / 2 - pt(hw_fs) / 2,
                     hw_text)
    hline(hw_top)

    # ── Row 5: Safety block (remaining height) ────────────────────────────
    safety_top = cur_top
    safety_bot = hw_top
    safety_h   = safety_top - safety_bot
    if safety_h < pic_size + 4 * mm:
        safety_h = pic_size + 4 * mm
        safety_bot = safety_top - safety_h

    # Adaptive pictogram sizing — shrink so ALL pictograms fit
    # Also cap to 20% of label width so phrases have enough room
    max_pic_for_width = w * 0.20
    pic_codes = r.get("pictogram_codes") or []
    n_pics = len(pic_codes)
    if n_pics > 0:
        gap = 1.5 * mm
        max_fit = (safety_h - gap * (n_pics + 1)) / n_pics
        adaptive_pic = min(pic_size, max_pic_for_width, max(max_fit, 3 * mm))
    else:
        adaptive_pic = min(pic_size, max_pic_for_width)
    pic_col_w = adaptive_pic + 2 * mm   # pictogram column width (tight)

    # Vertical divider between picto and phrases
    c.setLineWidth(LINE_W)
    c.setStrokeColor(BLACK)
    c.line(ox + pic_col_w, safety_bot, ox + pic_col_w, safety_top)

    # Pictograms — draw ALL
    _draw_pictograms(c, ox + 1 * mm, safety_bot, adaptive_pic,
                     safety_h, pic_codes, static_folder)

    # ── Multi-column phrase layout: H codes | P codes (overflow to extra cols) ─
    h_phrases = r.get("h_phrases") or []
    p_phrases = r.get("p_phrases") or []
    h_codes = [ph.get("code", "") for ph in h_phrases if ph.get("code")]
    p_codes = [ph.get("code", "") for ph in p_phrases if ph.get("code")]

    phrase_left  = ox + pic_col_w + PAD
    phrase_avail = w - pic_col_w - 2 * PAD

    # Signal word — spans full width
    signal = r.get("signal_word") or ""
    sig_y  = safety_top - pt(fs) - 1.5 * mm
    if signal:
        sig_color = RED if signal == "Danger" else WARN
        c.setFont("Helvetica-Bold", fs)
        c.setFillColor(sig_color)
        c.drawString(phrase_left, sig_y, signal.upper())
        phrase_top = sig_y - 1.0 * mm
    else:
        phrase_top = safety_top - 1.5 * mm

    usable_h = phrase_top - safety_bot - 0.5 * mm  # vertical space for codes

    # Helper: how many columns does a code list need at a given font size?
    def _cols_needed(codes_list, font_size):
        if not codes_list:
            return 0
        lh = pt(font_size) + 0.4 * mm
        rows_per_col = max(1, int(usable_h / lh))
        return -(-len(codes_list) // rows_per_col)   # ceil division

    # Adaptive font: shrink until H + P columns fit in phrase_avail width
    col_gap   = 0.8 * mm
    code_fs   = fb
    min_fs    = 3.0
    while code_fs > min_fs:
        n_h = max(1, _cols_needed(h_codes, code_fs)) if h_codes else 0
        n_p = max(1, _cols_needed(p_codes, code_fs)) if p_codes else 0
        n_total = n_h + n_p
        if n_total == 0:
            break
        # estimate column width from widest code
        test_w_h = max((c.stringWidth(cd, "Helvetica-Bold", code_fs) for cd in h_codes), default=0)
        test_w_p = max((c.stringWidth(cd, "Helvetica-Bold", code_fs) for cd in p_codes), default=0)
        total_w = n_h * (test_w_h + col_gap) + n_p * (test_w_p + col_gap)
        if total_w <= phrase_avail + col_gap:  # last col doesn't need trailing gap
            break
        code_fs -= 0.5

    line_h = pt(code_fs) + 0.4 * mm
    rows_per_col = max(1, int(usable_h / line_h))

    def _draw_code_columns(codes_list, start_x):
        """Draw codes in as many columns as needed, returns x after last column."""
        if not codes_list:
            return start_x
        col_w = max(c.stringWidth(cd, "Helvetica-Bold", code_fs) for cd in codes_list) + col_gap
        cx = start_x
        for col_idx in range(0, len(codes_list), rows_per_col):
            chunk = codes_list[col_idx:col_idx + rows_per_col]
            py = phrase_top - pt(code_fs)
            c.setFont("Helvetica-Bold", code_fs)
            c.setFillColor(BLACK)
            for code in chunk:
                if py < safety_bot:
                    break
                c.drawString(cx, py, code)
                py -= line_h
            cx += col_w
        return cx

    # Draw H columns then P columns
    x_after_h = _draw_code_columns(h_codes, phrase_left)

    # Vertical divider between H and P sections
    if h_codes and p_codes:
        div_x = x_after_h - col_gap / 2
        c.setLineWidth(0.4)
        c.setStrokeColor(DASH)
        c.line(div_x, safety_bot + 1 * mm, div_x, phrase_top + pt(code_fs) * 0.5)

    p_start = x_after_h if h_codes else phrase_left
    _draw_code_columns(p_codes, p_start)


# ── Pictogram rendering ───────────────────────────────────────────────────────

def _draw_pictograms(c: Canvas, col_x: float, col_bot: float,
                     size: float, col_h: float, codes: list[str],
                     static_folder: str | None) -> None:
    """Stack pictograms vertically top-to-bottom in the picto column."""
    if not codes:
        return
    gap     = 1.5 * mm
    step    = size + gap
    start_y = col_bot + col_h - size - gap

    for i, code in enumerate(codes):
        yy = start_y - i * step
        # Try PNG first
        if static_folder and _draw_png(c, col_x, yy, size, code, static_folder):
            continue
        # Fallback: vector diamond
        _draw_vector_diamond(c, col_x, yy, size, code)


def _draw_png(c: Canvas, bx: float, by: float, size: float,
              code: str, static_folder: str) -> bool:
    path = os.path.join(static_folder, "pictograms", f"{code}.png")
    if not os.path.isfile(path):
        return False
    try:
        c.drawImage(path, bx, by, width=size, height=size,
                    preserveAspectRatio=True, mask="auto")
        return True
    except Exception:
        return False


def _draw_vector_diamond(c: Canvas, bx: float, by: float,
                         size: float, code: str) -> None:
    """
    Draw a minimal GHS-style diamond with a letter symbol.
    Used when no PNG is available.
    """
    cx = bx + size / 2
    cy = by + size / 2
    r  = size * 0.47

    # White fill
    c.setFillColor(colors.white)
    c.setStrokeColor(colors.white)
    c.rect(bx, by, size, size, fill=1, stroke=0)

    # Red rotated square (diamond)
    c.saveState()
    c.translate(cx, cy)
    c.rotate(45)
    side = r * 2 * 0.71   # half-diagonal → side of inner square
    c.setStrokeColor(RED)
    c.setFillColor(colors.white)
    c.setLineWidth(max(0.5, size * 0.06))
    c.rect(-side / 2, -side / 2, side, side, fill=1, stroke=1)
    c.restoreState()

    # Symbol letter centred
    sym = GHS_FALLBACK.get(code, "?")
    sym_size = size * 0.45
    c.setFont("Helvetica-Bold", sym_size)
    c.setFillColor(RED)
    sw = c.stringWidth(sym, "Helvetica-Bold", sym_size)
    c.drawString(cx - sw / 2, by + size * 0.22, sym)
