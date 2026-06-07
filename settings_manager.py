"""Reads and writes settings.json, and handles invoice-number generation."""

import json
import os

# settings.json lives next to this file, so the app works no matter where
# it is launched from (and inside a PyInstaller .exe bundle too).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(BASE_DIR, "settings.json")

# CR-INV is the fixed invoice code (hardcoded by design).
INVOICE_CODE = "CR-INV"

# Roman numerals for months 1..12 -> I..XII
_ROMAN_MONTHS = [
    "I", "II", "III", "IV", "V", "VI",
    "VII", "VIII", "IX", "X", "XI", "XII",
]

DEFAULT_SETTINGS = {
    "company_name": "Chrone Studio",
    "company_tagline": "Photo • Booth • Event",
    "company_address_line_1": "JL Rajawali no.16 Jatimakmur Pondok",
    "company_address_line_2": "Gede Belasi Kode Pos 17413",
    "company_phone": "",
    "company_email": "",
    "company_instagram": "",
    "company_npwp": "",
    "logo_path": "assets/logo.png",
    "use_logo_image": False,
    "bank_name": "BCA",
    "bank_account_name": "MUHAMMAD ZIDANE P.",
    "bank_account_number": "6872489629",
    "official_statement": (
        "1. 50% sisa pembayaran wajib dilunasi paling lambat pada H+3 acara.\n"
        "2. DP yang telah dibayarkan dapat dikembalikan apabila pembatalan "
        "dilakukan maksimal H-7 sebelum acara."
    ),
    # Mandatory proforma disclaimer — keeps the document from being mistaken
    # for a Faktur Pajak (tax invoice). Printed verbatim in the footer.
    "proforma_disclaimer": (
        "Dokumen ini merupakan Proforma Invoice (penawaran harga / estimasi "
        "biaya) dan BUKAN Faktur Pajak. Harga sudah final dan tidak dikenakan "
        "PPN. Dokumen ini tidak mengikat secara hukum dan bukan bukti pembayaran."
    ),
    "thank_you_note": "Terima kasih atas kepercayaan Anda.",
    "closing_text": "Hormat kami,",
    "signature_name": "M ZIDANE PUSOKO",
    "show_terbilang": True,
    "terbilang_target": "total",
    # Last invoice number that was successfully generated. Next one is +1.
    # Starts at 15 so the first generated invoice is 16/CR-INV/...
    "last_invoice_number": 15,
}


def load_settings():
    """Return settings dict, creating settings.json with defaults if missing."""
    if not os.path.exists(SETTINGS_PATH):
        save_settings(DEFAULT_SETTINGS)
        return dict(DEFAULT_SETTINGS)

    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        # Corrupted file -> fall back to defaults rather than crashing.
        return dict(DEFAULT_SETTINGS)

    # Fill in any keys added in newer versions.
    merged = dict(DEFAULT_SETTINGS)
    merged.update(data)
    return merged


def save_settings(settings):
    """Write the settings dict to settings.json."""
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)


def _month_to_roman(month):
    return _ROMAN_MONTHS[month - 1]


def peek_next_invoice_no(settings, today):
    """Build the next invoice number string WITHOUT incrementing the counter.

    `today` is a datetime.date (passed in so the GUI and PDF stay in sync).
    Format: <seq>/CR-INV/<roman month>/<2-digit year>  e.g. 16/CR-INV/VI/26
    """
    seq = int(settings.get("last_invoice_number", 0)) + 1
    roman = _month_to_roman(today.month)
    year2 = today.year % 100
    return f"{seq}/{INVOICE_CODE}/{roman}/{year2:02d}"


def commit_invoice_no(settings, today):
    """Increment and persist the counter, returning the new invoice number.

    Call this only AFTER the PDF was generated successfully.
    """
    settings["last_invoice_number"] = int(settings.get("last_invoice_number", 0)) + 1
    save_settings(settings)
    roman = _month_to_roman(today.month)
    year2 = today.year % 100
    return f"{settings['last_invoice_number']}/{INVOICE_CODE}/{roman}/{year2:02d}"
