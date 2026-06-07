"""Generates the Pro Forma Invoice PDF with a fixed layout (ReportLab).

The layout imitates the reference design:
  - dashed border around the page
  - light-gray triangle accent top-left
  - logo + company info top-right
  - big "PRO FORMA INVOICE" title on the left
  - invoice info row
  - item table
  - DP / Total summary bottom-right
  - official statement + bank details bottom-left
  - signature bottom-right
"""

import os
import re

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

PAGE_W, PAGE_H = A4  # 595 x 842 points

# Colors
BLACK = (0.1, 0.1, 0.1)
GRAY = (0.55, 0.55, 0.55)
LIGHT_GRAY = (0.88, 0.88, 0.88)
LINE_GRAY = (0.8, 0.8, 0.8)
BORDER_RED = (0.86, 0.45, 0.45)

# Left/right content margins
LEFT = 45
RIGHT = PAGE_W - 45


def format_rupiah(value):
    """1500000 -> 'Rp 1.500.000'."""
    try:
        n = int(round(float(value)))
    except (ValueError, TypeError):
        n = 0
    s = f"{abs(n):,}".replace(",", ".")
    sign = "-" if n < 0 else ""
    return f"Rp {sign}{s}"


def clean_filename_part(text):
    """Make a string safe for a Windows filename."""
    text = text.strip()
    text = text.replace("/", "-").replace("\\", "-")
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r'[<>:"|?*]', "", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text or "untitled"


def _set_fill(c, rgb):
    c.setFillColorRGB(*rgb)


def _set_stroke(c, rgb):
    c.setStrokeColorRGB(*rgb)


def generate_invoice_pdf(data, settings, invoice_no):
    """Render the PDF and return its absolute file path.

    `data` keys:
        date, bill_to, items (list of {description, qty, amount}),
        dp_type ('No DP' | 'Percentage' | 'Fixed Amount'),
        dp_percentage (number), dp_amount (number)
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    filename = (
        f"invoice_{clean_filename_part(invoice_no)}_"
        f"{clean_filename_part(data.get('bill_to', ''))}.pdf"
    )
    path = os.path.join(OUTPUT_DIR, filename)

    c = canvas.Canvas(path, pagesize=A4)

    _draw_border(c)
    _draw_top_accent(c)
    y_after_header = _draw_company_header(c, settings)
    _draw_title(c)
    _draw_invoice_info(c, data, invoice_no)
    table_bottom = _draw_item_table(c, data)
    summary_bottom = _draw_summary(c, data, table_bottom)
    _draw_statement_and_bank(c, settings, summary_bottom)
    _draw_signature(c, settings, summary_bottom)

    c.showPage()
    c.save()
    return path


def _draw_border(c):
    _set_stroke(c, BORDER_RED)
    c.setLineWidth(1.2)
    c.setDash(3, 3)
    c.rect(20, 20, PAGE_W - 40, PAGE_H - 40, stroke=1, fill=0)
    c.setDash()  # reset


def _draw_top_accent(c):
    """Light-gray triangle in the top-left corner."""
    _set_fill(c, LIGHT_GRAY)
    p = c.beginPath()
    p.moveTo(20, PAGE_H - 20)
    p.lineTo(20 + 90, PAGE_H - 20)
    p.lineTo(20, PAGE_H - 20 - 90)
    p.close()
    c.drawPath(p, fill=1, stroke=0)


def _draw_company_header(c, settings):
    """Text wordmark + company name + address, top-right. Returns bottom y."""
    top = PAGE_H - 50

    # Draw the "CHRONE" text wordmark (no image logo) styled to resemble the
    # brand mark: a small angular accent + letter-spaced bold uppercase.
    wordmark_bottom = _draw_wordmark(c, settings, top)

    y = wordmark_bottom - 6
    _set_fill(c, BLACK)
    c.setFont("Helvetica-Bold", 12)
    c.drawRightString(RIGHT, y - 4, settings.get("company_name", ""))
    y -= 18
    _set_fill(c, GRAY)
    c.setFont("Helvetica", 8)
    addr1 = settings.get("company_address_line_1", "")
    addr2 = settings.get("company_address_line_2", "")
    if addr1:
        c.drawRightString(RIGHT, y, addr1)
        y -= 11
    if addr2:
        c.drawRightString(RIGHT, y, addr2)
        y -= 11
    return y


def _draw_wordmark(c, settings, top):
    """Draw a text-only 'CHRONE'-style wordmark in the top-right corner.

    The word is the first word of the company name, uppercased (so
    'Chrone Studio' -> 'CHRONE'), letter-spaced and bold, with a small
    angular accent mark to mimic the brand logo. Returns the bottom y.
    """
    company = (settings.get("company_name", "") or "").strip()
    word = (company.split()[0] if company else "CHRONE").upper()

    size = 17
    char_space = 1.5
    font = "Helvetica-Bold"
    base_w = c.stringWidth(word, font, size)
    total_w = base_w + char_space * (len(word) - 1)

    baseline = top - size
    x = RIGHT - total_w

    # small angular accent mark just left of the word (top-left corner bracket)
    mark_h = size * 0.62
    mark_w = 5
    mx = x - mark_w - 4
    my = baseline
    _set_stroke(c, BORDER_RED)
    c.setLineWidth(1.6)
    c.setDash()
    c.line(mx, my, mx, my + mark_h)            # vertical stroke
    c.line(mx, my + mark_h, mx + mark_w, my + mark_h)  # top horizontal stroke

    # the wordmark text, drawn char-by-char to apply letter spacing
    _set_fill(c, BLACK)
    c.setFont(font, size)
    cx = x
    for ch in word:
        c.drawString(cx, baseline, ch)
        cx += c.stringWidth(ch, font, size) + char_space

    return baseline


def _draw_title(c):
    _set_fill(c, BLACK)
    c.setFont("Helvetica-Bold", 28)
    c.drawString(LEFT, PAGE_H - 175, "PRO FORMA INVOICE")


def _draw_invoice_info(c, data, invoice_no):
    y = PAGE_H - 225
    _set_fill(c, BLACK)

    c.setFont("Helvetica-Bold", 9)
    c.drawString(LEFT, y, "Invoice No")
    c.setFont("Helvetica", 9)
    c.drawString(LEFT + 70, y, f": {invoice_no}")

    c.setFont("Helvetica-Bold", 9)
    c.drawString(PAGE_W - 230, y, "Date")
    c.setFont("Helvetica", 9)
    c.drawString(PAGE_W - 195, y, f": {data.get('date', '')}")

    y -= 18
    c.setFont("Helvetica-Bold", 9)
    c.drawString(LEFT, y, "Bill to")
    c.setFont("Helvetica", 9)
    c.drawString(LEFT + 70, y, f": {data.get('bill_to', '')}")


def _draw_item_table(c, data):
    """Draw the item table. Returns the y of the bottom line."""
    header_y = PAGE_H - 285

    # column x positions
    x_item = LEFT
    x_desc = LEFT + 45
    x_qty = PAGE_W - 200
    x_amount = RIGHT  # right-aligned

    # top separator line
    _set_stroke(c, LINE_GRAY)
    c.setLineWidth(0.8)
    c.line(LEFT, header_y + 14, RIGHT, header_y + 14)

    _set_fill(c, BLACK)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x_item, header_y, "Item")
    c.drawString(x_desc, header_y, "Description")
    c.drawString(x_qty, header_y, "Qty")
    c.drawRightString(x_amount, header_y, "Amount")

    # header bottom line
    c.line(LEFT, header_y - 8, RIGHT, header_y - 8)

    y = header_y - 28
    c.setFont("Helvetica", 9)
    items = data.get("items", [])
    for i, item in enumerate(items, start=1):
        desc = str(item.get("description", ""))
        qty = item.get("qty", 0)
        amount = item.get("amount", 0)

        _set_fill(c, BLACK)
        c.drawString(x_item, y, f"{i}.")

        # wrap long descriptions
        lines = _wrap_text(c, desc, "Helvetica", 9, x_qty - x_desc - 10)
        for j, line in enumerate(lines):
            c.drawString(x_desc, y - j * 11, line)

        c.drawString(x_qty, y, str(qty))
        c.drawRightString(x_amount, y, format_rupiah(float(qty) * float(amount)))

        row_height = max(22, len(lines) * 11 + 11)
        y -= row_height

    # bottom line under all items
    _set_stroke(c, LINE_GRAY)
    c.line(LEFT, y + 6, RIGHT, y + 6)
    return y + 6


def _draw_summary(c, data, table_bottom):
    """DP and Total, right aligned. Returns bottom y."""
    subtotal = sum(
        float(it.get("qty", 0)) * float(it.get("amount", 0))
        for it in data.get("items", [])
    )

    dp_type = data.get("dp_type", "No DP")
    if dp_type == "Percentage":
        pct = float(data.get("dp_percentage", 0) or 0)
        dp_amount = subtotal * pct / 100.0
        dp_label = f"DP {int(pct) if pct == int(pct) else pct}%"
    elif dp_type == "Fixed Amount":
        dp_amount = float(data.get("dp_amount", 0) or 0)
        dp_label = "DP"
    else:
        dp_amount = 0
        dp_label = None

    label_x = PAGE_W - 200
    value_x = RIGHT
    y = table_bottom - 25

    if dp_label is not None:
        _set_fill(c, BLACK)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(label_x, y, dp_label)
        c.setFont("Helvetica", 11)
        c.drawRightString(value_x, y, format_rupiah(dp_amount))
        y -= 20

    _set_fill(c, BLACK)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(label_x, y, "Total")
    c.setFont("Helvetica-Bold", 13)
    c.drawRightString(value_x, y, format_rupiah(subtotal))
    y -= 20
    return y


def _draw_statement_and_bank(c, settings, top_y):
    """Official statement + bank details on the lower-left."""
    y = top_y - 30
    _set_fill(c, BLACK)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(LEFT, y, "Official Statement")
    y -= 16

    _set_fill(c, GRAY)
    c.setFont("Helvetica", 7.5)
    for raw_line in settings.get("official_statement", "").split("\n"):
        for line in _wrap_text(c, raw_line, "Helvetica", 7.5, 300):
            c.drawString(LEFT, y, line)
            y -= 10

    y -= 16
    _set_fill(c, BLACK)
    c.setFont("Helvetica-Bold", 9)
    rows = [
        ("Bank Name", settings.get("bank_account_name", "")),
        ("Bank", settings.get("bank_name", "")),
        ("Bank Account", settings.get("bank_account_number", "")),
    ]
    for label, value in rows:
        c.setFont("Helvetica-Bold", 9)
        c.drawString(LEFT, y, label)
        c.setFont("Helvetica", 9)
        c.drawString(LEFT + 80, y, f": {value}")
        y -= 15
    return y


def _draw_signature(c, settings, top_y):
    """Closing text + signature name on the lower-right."""
    y = top_y - 30
    _set_fill(c, BLACK)
    c.setFont("Helvetica-Bold", 10)
    c.drawRightString(RIGHT, y, settings.get("closing_text", "Hormat Saya"))

    # space for a handwritten signature
    y -= 55
    c.setFont("Helvetica-Bold", 10)
    name = settings.get("signature_name", "")
    c.drawRightString(RIGHT, y, name)
    # underline-ish: a thin line above the name
    _set_stroke(c, LINE_GRAY)
    c.setLineWidth(0.6)
    text_w = c.stringWidth(name, "Helvetica-Bold", 10)
    c.line(RIGHT - text_w - 10, y + 12, RIGHT, y + 12)


def _wrap_text(c, text, font, size, max_width):
    """Greedy word wrap; returns a list of lines."""
    if not text:
        return [""]
    words = text.split(" ")
    lines = []
    current = ""
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
