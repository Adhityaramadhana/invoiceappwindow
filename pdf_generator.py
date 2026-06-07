"""Generates the Chrone Pro Forma Invoice PDF (ReportLab).

Redesigned per the unified brand/cognitive-design blueprint:
  - pure white A4 background (mandatory)
  - "Chrone" wordmark with a drawn clock-face "o" (single orange accent)
  - clean typographic hierarchy, low-ink table, payment cascade
    (Subtotal / Diskon / Total / DP / Sisa Pembayaran)
  - Indonesian labels; clear proforma disclaimer (not a Faktur Pajak)
"""

import math
import os
import re

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

# ---------------------------------------------------------------------------
# Brand tokens (RGB 0..1). Mirror of the GUI hex palette.
# ---------------------------------------------------------------------------
ORANGE = (0.949, 0.416, 0.106)      # #F26A1B — the ONLY accent
INK = (0.118, 0.118, 0.133)         # #1E1E22 — primary text
GRAY_700 = (0.290, 0.290, 0.322)    # #4A4A52 — body / values
GRAY_400 = (0.541, 0.541, 0.576)    # #8A8A93 — labels / captions
GRAY_200 = (0.847, 0.847, 0.871)    # #D8D8DE — hairlines
GRAY_100 = (0.937, 0.937, 0.945)    # #EFEFF1 — zebra (>6 rows)

# Type scale (pt)
T_TITLE = 26
T_WORD = 18
T_TOTAL = 14
T_H2 = 11
T_BODY = 9.5
T_LABEL = 8
T_CAPTION = 7.5

# Page grid
PAGE_W, PAGE_H = A4                  # 595 x 842 pt
MARGIN = 48
LEFT = 48
RIGHT = PAGE_W - MARGIN              # 547 — shared right edge
SUMMARY_LABEL_X = 360               # left edge of the right-hand summary zone

FONT = "Helvetica"
FONT_B = "Helvetica-Bold"
FONT_I = "Helvetica-Oblique"

MINUS = "−"  # proper minus sign


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------
def format_rupiah(value):
    """1500000 -> 'Rp 1.500.000'."""
    try:
        n = int(round(float(value)))
    except (ValueError, TypeError):
        n = 0
    s = f"{abs(n):,}".replace(",", ".")
    sign = "-" if n < 0 else ""
    return f"Rp {sign}{s}"


_SATUAN = [
    "", "satu", "dua", "tiga", "empat", "lima",
    "enam", "tujuh", "delapan", "sembilan", "sepuluh", "sebelas",
]


def _terbilang(n):
    if n < 12:
        return " " + _SATUAN[n]
    if n < 20:
        return _terbilang(n - 10) + " belas"
    if n < 100:
        return _terbilang(n // 10) + " puluh" + _terbilang(n % 10)
    if n < 200:
        return " seratus" + _terbilang(n - 100)
    if n < 1000:
        return _terbilang(n // 100) + " ratus" + _terbilang(n % 100)
    if n < 2000:
        return " seribu" + _terbilang(n - 1000)
    if n < 1_000_000:
        return _terbilang(n // 1000) + " ribu" + _terbilang(n % 1000)
    if n < 1_000_000_000:
        return _terbilang(n // 1_000_000) + " juta" + _terbilang(n % 1_000_000)
    if n < 1_000_000_000_000:
        return _terbilang(n // 1_000_000_000) + " miliar" + _terbilang(n % 1_000_000_000)
    return _terbilang(n // 1_000_000_000_000) + " triliun" + _terbilang(n % 1_000_000_000_000)


def terbilang(value):
    """1500000 -> 'Satu Juta Lima Ratus Ribu Rupiah'."""
    n = int(round(abs(float(value or 0))))
    words = "nol" if n == 0 else re.sub(r"\s+", " ", _terbilang(n)).strip()
    return f"{words} rupiah".title()


def _fmt_pct(pct):
    return str(int(pct)) if float(pct) == int(pct) else f"{pct:g}"


def compute_totals(items, dp_type="No DP", dp_percentage=0, dp_amount=0, diskon=0):
    """Single source of truth for the money math (shared by GUI + PDF).

    Returns: subtotal, diskon, total, dp_amount, dp_label, sisa, show_sisa.
    """
    subtotal = 0.0
    for it in items:
        try:
            subtotal += float(it.get("qty", 0)) * float(it.get("amount", 0))
        except (ValueError, TypeError):
            continue
    diskon = max(0.0, float(diskon or 0))
    total = max(0.0, subtotal - diskon)

    show_sisa = dp_type != "No DP"
    if dp_type == "Percentage":
        pct = float(dp_percentage or 0)
        dpa = total * pct / 100.0
        dp_label = f"DP (Uang Muka) {_fmt_pct(pct)}%"
    elif dp_type == "Fixed Amount":
        dpa = float(dp_amount or 0)
        dp_label = "DP (Uang Muka)"
    else:
        dpa = 0.0
        dp_label = None
    sisa = total - dpa
    return {
        "subtotal": subtotal,
        "diskon": diskon,
        "total": total,
        "dp_amount": dpa,
        "dp_label": dp_label,
        "sisa": sisa,
        "show_sisa": show_sisa,
    }


def clean_filename_part(text):
    """Make a string safe for a Windows filename."""
    text = (text or "").strip()
    text = text.replace("/", "-").replace("\\", "-")
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r'[<>:"|?*]', "", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text or "untitled"


def suggest_filename(invoice_no, bill_to):
    """Default PDF filename, e.g. invoice_16-CR-INV-VI-26_Ka-Ara.pdf."""
    return f"invoice_{clean_filename_part(invoice_no)}_{clean_filename_part(bill_to)}.pdf"


# ---------------------------------------------------------------------------
# Low-level drawing helpers
# ---------------------------------------------------------------------------
def _fill(c, rgb):
    c.setFillColorRGB(*rgb)


def _stroke(c, rgb):
    c.setStrokeColorRGB(*rgb)


def _hairline(c, x1, y, x2, color=GRAY_200, w=0.75):
    _stroke(c, color)
    c.setLineWidth(w)
    c.setDash()
    c.line(x1, y, x2, y)


def _label(c, x, y, text, color=GRAY_400, size=T_LABEL, tracking=0.4, align="left"):
    """Draw an uppercase tracked label. Returns its drawn width."""
    text = text.upper()
    width = c.stringWidth(text, FONT_B, size) + tracking * max(0, len(text) - 1)
    if align == "right":
        start = x - width
    elif align == "center":
        start = x - width / 2
    else:
        start = x
    _fill(c, color)
    c.setFont(FONT_B, size)
    cx = start
    for ch in text:
        c.drawString(cx, y, ch)
        cx += c.stringWidth(ch, FONT_B, size) + tracking
    return width


def _wrap_text(c, text, font, size, max_width):
    """Greedy word wrap; returns a list of lines."""
    if not text:
        return [""]
    words = str(text).split(" ")
    lines, current = [], ""
    for w in words:
        trial = w if not current else current + " " + w
        if c.stringWidth(trial, font, size) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = w
    if current:
        lines.append(current)
    return lines


# ---------------------------------------------------------------------------
# Wordmark with clock-face "o"
# ---------------------------------------------------------------------------
def _clock_hand(c, cx, cy, length, theta_clock_deg, width):
    a = math.radians(90 - theta_clock_deg)
    _stroke(c, INK)
    c.setLineWidth(width)
    c.setLineCap(1)
    c.line(cx, cy, cx + length * math.cos(a), cy + length * math.sin(a))


def _draw_wordmark(c, settings, right=RIGHT, baseline=800):
    """Draw mixed-case 'Chrone' with the 'o' as an orange clock face."""
    company = (settings.get("company_name", "") or "Chrone").strip()
    word = company.split()[0] if company else "Chrone"
    word = word[:1].upper() + word[1:].lower()

    s = T_WORD
    i = word.lower().find("o")
    if i == -1:
        c.setFont(FONT_B, s)
        _fill(c, INK)
        c.drawRightString(right, baseline, word)
        return baseline

    pre, post = word[:i], word[i + 1:]
    d = s * 0.66
    r = d / 2
    cy = baseline + r * 0.86
    w_pre = c.stringWidth(pre, FONT_B, s)
    w_o = d + 2
    w_post = c.stringWidth(post, FONT_B, s)
    x = right - (w_pre + w_o + w_post)

    c.setFont(FONT_B, s)
    _fill(c, INK)
    c.drawString(x, baseline, pre)

    ox = x + w_pre + w_o / 2
    c.setLineWidth(2.2)
    _stroke(c, ORANGE)
    c.circle(ox, cy, r, stroke=1, fill=0)
    _clock_hand(c, ox, cy, 0.30 * r, 155, 1.4)   # hour ~10
    _clock_hand(c, ox, cy, 0.55 * r, 60, 1.2)    # minute ~2  -> 10:10
    _fill(c, INK)
    c.circle(ox, cy, 0.9, stroke=0, fill=1)      # hub

    _fill(c, INK)
    c.drawString(x + w_pre + w_o, baseline, post)
    return baseline


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------
def _draw_header(c, settings):
    """Identity block, top-right."""
    _draw_wordmark(c, settings, baseline=800)

    _fill(c, INK)
    c.setFont(FONT_B, T_H2)
    c.drawRightString(RIGHT, 783, settings.get("company_name", ""))

    y = 772
    tagline = (settings.get("company_tagline", "") or "").strip()
    if tagline:
        _fill(c, GRAY_400)
        c.setFont(FONT_I, T_CAPTION)
        c.drawRightString(RIGHT, y, tagline)
        y -= 10

    _fill(c, GRAY_400)
    c.setFont(FONT, T_CAPTION)
    for key in ("company_address_line_1", "company_address_line_2"):
        line = (settings.get(key, "") or "").strip()
        if line:
            c.drawRightString(RIGHT, y, line)
            y -= 10

    # contact cluster
    parts = []
    phone = (settings.get("company_phone", "") or "").strip()
    email = (settings.get("company_email", "") or "").strip()
    ig = (settings.get("company_instagram", "") or "").strip().lstrip("@")
    if phone:
        parts.append(f"WA {phone}")
    if email:
        parts.append(email)
    if ig:
        parts.append(f"@{ig}")
    if parts:
        _fill(c, GRAY_400)
        c.setFont(FONT, T_CAPTION)
        c.drawRightString(RIGHT, y, "   ·   ".join(parts))


def _draw_title(c):
    _fill(c, INK)
    c.setFont(FONT_B, T_TITLE)
    c.drawString(LEFT, 720, "Pro Forma Invoice")
    _fill(c, GRAY_400)
    c.setFont(FONT_I, T_CAPTION)
    c.drawString(LEFT, 706, "Dokumen ini adalah Proforma Invoice, bukan Faktur Pajak.")


def _draw_meta(c, data, invoice_no):
    """No. Proforma / Tanggal / Kepada Yth. / Masa Berlaku / Jatuh Tempo."""
    val_l_x = LEFT + 92

    def right_value(label_text, value, y):
        # right-aligned value at RIGHT, label at the left of the right column
        _label(c, SUMMARY_LABEL_X, y, label_text)
        _fill(c, INK)
        c.setFont(FONT, T_BODY)
        c.drawRightString(RIGHT, y, value)

    # Row A
    _label(c, LEFT, 682, "No. Proforma")
    _fill(c, INK)
    c.setFont(FONT, T_BODY)
    c.drawString(val_l_x, 682, invoice_no)
    right_value("Tanggal", data.get("date", ""), 682)

    # Row B
    _label(c, LEFT, 664, "Kepada Yth.")
    _fill(c, INK)
    c.setFont(FONT_B, T_BODY)
    c.drawString(val_l_x, 664, data.get("bill_to", ""))
    validity = (data.get("validity", "") or "").strip()
    if validity:
        right_value("Masa Berlaku", validity, 664)

    # Row C
    due = (data.get("due_date", "") or "").strip()
    if due:
        right_value("Jatuh Tempo", due, 646)

    _hairline(c, LEFT, 636, RIGHT)


def _draw_table(c, data):
    """Low-ink item table. Returns bottom y."""
    x_idx, x_desc, x_qty, x_amt = LEFT, LEFT + 30, 400, RIGHT
    desc_max_w = 350 - x_desc

    head_y = 612
    _label(c, x_idx, head_y, "#")
    _label(c, x_desc, head_y, "Deskripsi")
    _label(c, x_qty, head_y, "Qty", align="center")
    _label(c, x_amt, head_y, "Jumlah", align="right")
    _hairline(c, LEFT, head_y - 8, RIGHT)

    y = head_y - 26
    items = data.get("items", [])
    for i, item in enumerate(items, start=1):
        qty = item.get("qty", 0)
        amount = item.get("amount", 0)
        lines = _wrap_text(c, item.get("description", ""), FONT, T_BODY, desc_max_w)

        _fill(c, GRAY_400)
        c.setFont(FONT, T_BODY)
        c.drawString(x_idx, y, str(i))

        _fill(c, GRAY_700)
        c.setFont(FONT, T_BODY)
        for j, line in enumerate(lines):
            c.drawString(x_desc, y - j * 12, line)
        c.drawCentredString(x_qty, y, str(qty))
        try:
            line_total = float(qty) * float(amount)
        except (ValueError, TypeError):
            line_total = 0
        c.drawRightString(x_amt, y, format_rupiah(line_total))

        row_h = max(22, len(lines) * 12 + 10)
        y -= row_h

    bottom = y + 10
    _hairline(c, LEFT, bottom, RIGHT)
    return bottom


def _draw_summary(c, totals, top_y):
    """Payment cascade in the right zone. Returns bottom y."""
    label_x = SUMMARY_LABEL_X
    val_x = RIGHT
    y = top_y - 24

    def line(label_text, value_text, bold=False, value_color=GRAY_700):
        nonlocal y
        if bold:
            _fill(c, INK)
            c.setFont(FONT_B, T_H2)
            c.drawString(label_x, y, label_text)
            _fill(c, value_color)
            c.setFont(FONT_B, T_TOTAL)
            c.drawRightString(val_x, y, value_text)
        else:
            _fill(c, GRAY_700)
            c.setFont(FONT, T_BODY)
            c.drawString(label_x, y, label_text)
            _fill(c, GRAY_700)
            c.setFont(FONT, T_BODY)
            c.drawRightString(val_x, y, value_text)

    line("Subtotal", format_rupiah(totals["subtotal"]))
    y -= 18
    if totals["diskon"] > 0:
        line("Diskon", f"{MINUS} {format_rupiah(totals['diskon'])}")
        y -= 18

    y -= 2
    _hairline(c, label_x, y + 6, val_x)
    y -= 12

    # Total (grand price) — the single orange accent: underline its value
    total_str = format_rupiah(totals["total"])
    line("Total", total_str, bold=True, value_color=INK)
    tw = c.stringWidth(total_str, FONT_B, T_TOTAL)
    _stroke(c, ORANGE)
    c.setLineWidth(2.5)
    c.setDash()
    c.line(val_x - tw, y - 5, val_x, y - 5)
    y -= 22

    if totals["show_sisa"]:
        line(totals["dp_label"] or "DP (Uang Muka)",
             f"{MINUS} {format_rupiah(totals['dp_amount'])}")
        y -= 20
        line("Sisa Pembayaran", format_rupiah(totals["sisa"]),
             bold=True, value_color=INK)
        y -= 22

    return y


def _draw_terbilang(c, settings, totals, top_y):
    """Amount-in-words line, full width. Returns bottom y."""
    if not settings.get("show_terbilang", True):
        return top_y
    target = settings.get("terbilang_target", "total")
    value = totals["sisa"] if (target == "sisa" and totals["show_sisa"]) else totals["total"]
    words = f"# {terbilang(value)} #"

    y = top_y - 16
    wlabel = _label(c, LEFT, y, "Terbilang:")
    _fill(c, INK)
    c.setFont(FONT_I, T_BODY)
    text_x = LEFT + wlabel + 8
    for line in _wrap_text(c, words, FONT_I, T_BODY, RIGHT - text_x):
        c.drawString(text_x, y, line)
        y -= 12
    return y


def _draw_footer(c, settings, top_y=196):
    """Two-column footer anchored near the bottom margin."""
    _hairline(c, LEFT, top_y, RIGHT)

    # ---- Left: payment + notes + disclaimer ----
    lx = LEFT
    ly = top_y - 16
    _label(c, lx, ly, "Pembayaran")
    ly -= 14
    _fill(c, GRAY_700)
    bank_rows = [
        ("Bank", settings.get("bank_name", "")),
        ("No. Rekening", settings.get("bank_account_number", "")),
        ("a.n.", settings.get("bank_account_name", "")),
    ]
    for lab, val in bank_rows:
        c.setFont(FONT_B, T_CAPTION)
        c.drawString(lx, ly, lab)
        c.setFont(FONT, T_CAPTION)
        c.drawString(lx + 64, ly, str(val))
        ly -= 12

    ly -= 6
    _label(c, lx, ly, "Catatan")
    ly -= 13
    _fill(c, GRAY_400)
    c.setFont(FONT, T_CAPTION)
    statement = (settings.get("official_statement", "") or "").strip()
    for raw in statement.split("\n"):
        for line in _wrap_text(c, raw, FONT, T_CAPTION, 300):
            c.drawString(lx, ly, line)
            ly -= 10

    disclaimer = (settings.get("proforma_disclaimer", "") or "").strip()
    if disclaimer:
        ly -= 4
        _fill(c, INK)
        c.setFont(FONT_I, 6.6)
        for line in _wrap_text(c, disclaimer, FONT_I, 6.6, 300):
            c.drawString(lx, ly, line)
            ly -= 9

    # ---- Right: closing + signature ----
    rx = RIGHT
    ry = top_y - 16
    thanks = (settings.get("thank_you_note", "") or "").strip()
    if thanks:
        _fill(c, GRAY_400)
        c.setFont(FONT_I, T_CAPTION)
        c.drawRightString(rx, ry, thanks)
        ry -= 16
    _fill(c, GRAY_700)
    c.setFont(FONT, T_BODY)
    c.drawRightString(rx, ry, settings.get("closing_text", "Hormat kami,"))

    ry -= 52
    name = settings.get("signature_name", "")
    nw = c.stringWidth(name, FONT_B, T_BODY)
    _hairline(c, rx - max(nw, 110), ry + 12, rx, color=GRAY_200, w=0.6)
    _fill(c, INK)
    c.setFont(FONT_B, T_BODY)
    c.drawRightString(rx, ry, name)
    ry -= 12
    _fill(c, GRAY_400)
    c.setFont(FONT, T_CAPTION)
    c.drawRightString(rx, ry, settings.get("company_name", ""))


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def generate_invoice_pdf(data, settings, invoice_no, output_path=None):
    """Render the PDF and return its absolute file path.

    `data` keys: date, bill_to, items[{description,qty,amount}], dp_type,
    dp_percentage, dp_amount, and optionally diskon, due_date, validity.
    """
    if output_path:
        path = output_path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    else:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        path = os.path.join(
            OUTPUT_DIR, suggest_filename(invoice_no, data.get("bill_to", ""))
        )

    totals = compute_totals(
        data.get("items", []),
        data.get("dp_type", "No DP"),
        data.get("dp_percentage", 0),
        data.get("dp_amount", 0),
        data.get("diskon", 0),
    )

    c = canvas.Canvas(path, pagesize=A4)  # default page is pure white
    _draw_header(c, settings)
    _draw_title(c)
    _draw_meta(c, data, invoice_no)
    table_bottom = _draw_table(c, data)
    summary_bottom = _draw_summary(c, totals, table_bottom)
    _draw_terbilang(c, settings, totals, summary_bottom)
    _draw_footer(c, settings)
    c.showPage()
    c.save()
    return path
