"""Chrone Pro Forma Invoice Generator — CustomTkinter GUI.

Redesigned per the brand/cognitive-design blueprint:
  - fixed header strip with the Chrone clock wordmark + segmented nav
  - input grouped into clean cards (proximity / chunking)
  - a sticky Live Summary panel (Subtotal / Diskon / DP / Sisa / Total) that
    updates as you type — immediate feedback, fewer errors
  - 3-tier button hierarchy; the orange primary is the single strong accent
"""

import datetime
import os
import re
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk
from tkcalendar import DateEntry

import history_manager as hm
import settings_manager as sm
from pdf_generator import (
    OUTPUT_DIR,
    compute_totals,
    generate_invoice_pdf,
    suggest_filename,
)

# --------------------------------------------------------------------------- #
# Brand palette (mirror of the PDF tokens)
# --------------------------------------------------------------------------- #
ORANGE = "#F26A1B"
ORANGE_DARK = "#D4570F"
ORANGE_TINT = "#FDE7D6"
INK = "#1E1E22"
GRAY_700 = "#4A4A52"
GRAY_400 = "#8A8A93"
GRAY_200 = "#D8D8DE"
APP_BG = "#F4F5F7"
CARD = "#FFFFFF"
CARD_ALT = "#FAFAFB"
DANGER = "#D23B3B"
OK = "#2E9E5B"

DP_SEG = ["Tanpa DP", "Persentase", "Nominal"]
DP_MAP = {"Tanpa DP": "No DP", "Persentase": "Percentage", "Nominal": "Fixed Amount"}

_ID_MONTHS = [
    "", "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
]


def format_date_indonesian(d):
    return f"{d.day:02d} {_ID_MONTHS[d.month]} {d.year}"


def to_number(s):
    """Parse '1.500.000' / 'Rp 1.500.000' -> 1500000.0 (integer rupiah)."""
    s = re.sub(r"[^0-9]", "", (s or ""))
    return float(s) if s else 0.0


def to_pct(s):
    s = (s or "").strip().replace(",", ".")
    s = re.sub(r"[^0-9.]", "", s)
    try:
        return max(0.0, min(100.0, float(s)))
    except ValueError:
        return 0.0


def rupiah(v):
    return "Rp " + f"{int(round(v)):,}".replace(",", ".")


# --------------------------------------------------------------------------- #
# Item row
# --------------------------------------------------------------------------- #
class ItemRow:
    def __init__(self, parent, on_remove, on_change, fonts):
        self.on_remove = on_remove
        self.on_change = on_change
        self.frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.frame.pack(fill="x", pady=3)

        self.desc_var = tk.StringVar()
        self.qty_var = tk.StringVar(value="1")
        self.amt_var = tk.StringVar()

        self.description = ctk.CTkEntry(
            self.frame, textvariable=self.desc_var, font=fonts["body"],
            placeholder_text="mis. 2 Hour Package + 1 Hour Free", height=34,
        )
        self.description.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.qty = ctk.CTkComboBox(
            self.frame, variable=self.qty_var, width=72, height=34,
            values=[str(i) for i in range(1, 21)], font=fonts["body"],
            command=lambda _v: self.on_change(),
        )
        self.qty.pack(side="left", padx=(0, 6))

        self.amount = ctk.CTkEntry(
            self.frame, textvariable=self.amt_var, width=120, justify="right",
            font=fonts["body"], placeholder_text="0", height=34,
        )
        self.amount.pack(side="left", padx=(0, 6))

        self.remove_btn = ctk.CTkButton(
            self.frame, text="✕", width=30, height=30, font=fonts["body"],
            fg_color="transparent", text_color=GRAY_400, hover_color="#F3D6D6",
            command=lambda: self.on_remove(self),
        )
        self.remove_btn.pack(side="left")

        self.qty_var.trace_add("write", lambda *_: self.on_change())
        self.amt_var.trace_add("write", lambda *_: self.on_change())
        self.amount.bind("<FocusOut>", self._fmt_amount)
        self.amount.bind("<FocusIn>", self._raw_amount)

    def _fmt_amount(self, _e=None):
        raw = self.amt_var.get().strip()
        if raw:
            self.amt_var.set(f"{int(to_number(raw)):,}".replace(",", "."))

    def _raw_amount(self, _e=None):
        raw = self.amt_var.get().strip()
        if raw:
            self.amt_var.set(str(int(to_number(raw))))

    def show_remove(self, visible):
        if visible:
            self.remove_btn.pack(side="left")
        else:
            self.remove_btn.pack_forget()

    def is_blank(self):
        return not self.desc_var.get().strip() and not self.amt_var.get().strip()

    def values(self):
        return {
            "description": self.desc_var.get().strip(),
            "qty": int(to_number(self.qty_var.get()) or 0),
            "amount": to_number(self.amt_var.get()),
        }

    def destroy(self):
        self.frame.destroy()


# --------------------------------------------------------------------------- #
# Main app
# --------------------------------------------------------------------------- #
class InvoiceApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("light")
        self.title("Chrone — Pro Forma Invoice")
        self.geometry("960x740")
        self.minsize(860, 660)
        self.configure(fg_color=APP_BG)

        self.settings = sm.load_settings()
        self.item_rows = []
        self._editing_id = None  # id of the history record being edited, if any
        self.fonts = {
            "title": ctk.CTkFont(size=22, weight="bold"),
            "word": ctk.CTkFont(size=19, weight="bold"),
            "h2": ctk.CTkFont(size=14, weight="bold"),
            "total": ctk.CTkFont(size=19, weight="bold"),
            "body": ctk.CTkFont(size=13),
            "body_b": ctk.CTkFont(size=13, weight="bold"),
            "label": ctk.CTkFont(size=11, weight="bold"),
            "caption": ctk.CTkFont(size=11),
        }

        self._build_header()

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        self.create_page = ctk.CTkFrame(self.body, fg_color="transparent")
        self.history_page = ctk.CTkFrame(self.body, fg_color="transparent")
        self.settings_page = ctk.CTkFrame(self.body, fg_color="transparent")
        self._build_create_page(self.create_page)
        self._build_history_page(self.history_page)
        self._build_settings_page(self.settings_page)

        self._show_page("Create Invoice")
        self._add_item_row()
        self._recalc()
        self._refresh_invoice_no()

    # ----- header / nav ----------------------------------------------------- #
    def _build_header(self):
        bar = ctk.CTkFrame(self, fg_color=APP_BG, height=60)
        bar.pack(fill="x", padx=16, pady=(12, 8))

        left = ctk.CTkFrame(bar, fg_color="transparent")
        left.pack(side="left")
        ctk.CTkLabel(left, text="Chr", text_color=INK, font=self.fonts["word"]).pack(side="left")
        clock = tk.Canvas(left, width=20, height=24, bg=APP_BG, highlightthickness=0, bd=0)
        clock.pack(side="left", pady=(2, 0))
        cx, cy, r = 10, 13, 7
        clock.create_oval(cx - r, cy - r, cx + r, cy + r, outline=ORANGE, width=2)
        clock.create_line(cx, cy, cx - 2.5, cy - 2.0, fill=INK, width=2)   # hour ~10
        clock.create_line(cx, cy, cx + 3.5, cy - 1.5, fill=INK, width=1)   # minute ~2
        clock.create_oval(cx - 1, cy - 1, cx + 1, cy + 1, fill=INK, outline=INK)
        ctk.CTkLabel(left, text="ne", text_color=INK, font=self.fonts["word"]).pack(side="left")
        ctk.CTkLabel(
            left, text="  Pro Forma Invoice", text_color=GRAY_400,
            font=self.fonts["body"],
        ).pack(side="left")

        self.nav_var = tk.StringVar(value="Create Invoice")
        nav = ctk.CTkSegmentedButton(
            bar, values=["Create Invoice", "Riwayat", "Settings"], variable=self.nav_var,
            command=self._show_page, font=self.fonts["body_b"],
            selected_color=ORANGE, selected_hover_color=ORANGE_DARK,
            unselected_color="#E4E6EA", text_color=INK,
            unselected_hover_color="#D8DAE0",
        )
        nav.pack(side="right")

    def _show_page(self, name):
        self.nav_var.set(name)
        for p in (self.create_page, self.history_page, self.settings_page):
            p.pack_forget()
        pages = {
            "Create Invoice": self.create_page,
            "Riwayat": self.history_page,
            "Settings": self.settings_page,
        }
        pages.get(name, self.create_page).pack(fill="both", expand=True)
        if name == "Riwayat":
            self._refresh_history()

    # ----- card factory ----------------------------------------------------- #
    def _make_card(self, parent, title):
        card = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=12,
                            border_width=1, border_color=GRAY_200)
        card.pack(fill="x", pady=(0, 12))
        if title:
            ctk.CTkLabel(card, text=title, text_color=INK, font=self.fonts["h2"],
                         anchor="w").pack(fill="x", padx=16, pady=(12, 0))
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=12)
        return inner

    def _labeled_row(self, parent, label):
        """Create a row with a left-aligned label; widgets pack into the row."""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=4)
        ctk.CTkLabel(row, text=label, text_color=GRAY_400, font=self.fonts["label"],
                     width=130, anchor="w").pack(side="left")
        return row

    # ----- create page ------------------------------------------------------ #
    def _build_create_page(self, page):
        page.grid_columnconfigure(0, weight=1)
        page.grid_columnconfigure(1, weight=0, minsize=300)
        page.grid_rowconfigure(0, weight=1)

        left = ctk.CTkScrollableFrame(page, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))

        right = ctk.CTkFrame(page, fg_color="transparent", width=300)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_propagate(False)

        # --- Card: Detail Invoice ---
        c = self._make_card(left, "Detail Invoice")
        self.edit_status = ctk.CTkLabel(
            c, text="", text_color=ORANGE_DARK, font=self.fonts["caption"], anchor="w")
        self.edit_status.pack(fill="x")
        rid = ctk.CTkFrame(c, fg_color="transparent")
        rid.pack(fill="x", pady=4)
        ctk.CTkLabel(rid, text="NO. PROFORMA", text_color=GRAY_400,
                     font=self.fonts["label"], width=130, anchor="w").pack(side="left")
        self.invoice_no_var = tk.StringVar()
        self._invoice_no_touched = False
        inv_entry = ctk.CTkEntry(
            rid, textvariable=self.invoice_no_var, font=self.fonts["body_b"],
            height=32, placeholder_text="mis. 16/CR-INV/VI/26")
        inv_entry.pack(side="left", fill="x", expand=True)
        # Manual field: typing marks it "touched" so the date-based suggestion
        # stops overwriting it.
        inv_entry.bind("<KeyRelease>",
                       lambda _e: setattr(self, "_invoice_no_touched", True))

        rdate = ctk.CTkFrame(c, fg_color="transparent")
        rdate.pack(fill="x", pady=4)
        ctk.CTkLabel(rdate, text="TANGGAL", text_color=GRAY_400,
                     font=self.fonts["label"], width=130, anchor="w").pack(side="left")
        self.date_picker = DateEntry(
            rdate, date_pattern="dd/MM/yyyy", width=14, justify="center",
            background=ORANGE, foreground="white", borderwidth=2,
            headersbackground=ORANGE, headersforeground="white",
            selectbackground=ORANGE, font=("Helvetica", 11),
        )
        self.date_picker.pack(side="left")
        self.date_picker.bind("<<DateEntrySelected>>", lambda _e: self._refresh_invoice_no())

        # --- Card: Kepada Yth. ---
        c = self._make_card(left, "Kepada Yth.")
        self.bill_to_var = tk.StringVar()
        self.bill_to_entry = ctk.CTkEntry(
            c, textvariable=self.bill_to_var, font=self.fonts["body"], height=34,
            placeholder_text="Nama klien atau perusahaan")
        self.bill_to_entry.pack(fill="x")
        self.bill_to_var.trace_add("write", lambda *_: self._recalc())

        # --- Card: Item ---
        card = ctk.CTkFrame(left, fg_color=CARD, corner_radius=12,
                            border_width=1, border_color=GRAY_200)
        card.pack(fill="x", pady=(0, 12))
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(12, 0))
        ctk.CTkLabel(head, text="Item", text_color=INK, font=self.fonts["h2"]).pack(side="left")
        ctk.CTkButton(
            head, text="＋ Tambah item", width=130, height=30, font=self.fonts["body_b"],
            fg_color="transparent", text_color=ORANGE, border_width=1,
            border_color=ORANGE, hover_color=ORANGE_TINT, command=self._add_item_row,
        ).pack(side="right")

        caps = ctk.CTkFrame(card, fg_color="transparent")
        caps.pack(fill="x", padx=16, pady=(8, 0))
        ctk.CTkLabel(caps, text="DESKRIPSI", text_color=GRAY_400,
                     font=self.fonts["label"], anchor="w").pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(caps, text="QTY", text_color=GRAY_400, font=self.fonts["label"],
                     width=72).pack(side="left", padx=(0, 6))
        ctk.CTkLabel(caps, text="HARGA", text_color=GRAY_400, font=self.fonts["label"],
                     width=120, anchor="e").pack(side="left", padx=(0, 36))
        self.items_container = ctk.CTkFrame(card, fg_color="transparent")
        self.items_container.pack(fill="x", padx=16, pady=(4, 14))

        # --- Card: Pembayaran & DP ---
        c = self._make_card(left, "Pembayaran & DP")
        drow = ctk.CTkFrame(c, fg_color="transparent")
        drow.pack(fill="x", pady=4)
        ctk.CTkLabel(drow, text="JENIS DP", text_color=GRAY_400,
                     font=self.fonts["label"], width=130, anchor="w").pack(side="left")
        self.dp_var = tk.StringVar(value="Tanpa DP")
        ctk.CTkSegmentedButton(
            drow, values=DP_SEG, variable=self.dp_var, command=self._on_dp_change,
            font=self.fonts["body"], selected_color=ORANGE,
            selected_hover_color=ORANGE_DARK, unselected_color="#E4E6EA",
            text_color=INK,
        ).pack(side="left")

        self.dp_value_row = ctk.CTkFrame(c, fg_color="transparent")
        ctk.CTkLabel(self.dp_value_row, text="NILAI DP", text_color=GRAY_400,
                     font=self.fonts["label"], width=130, anchor="w").pack(side="left")
        self.dp_value_var = tk.StringVar()
        self.dp_value_entry = ctk.CTkEntry(
            self.dp_value_row, textvariable=self.dp_value_var, width=140,
            font=self.fonts["body"], height=32)
        self.dp_value_entry.pack(side="left")
        self.dp_suffix = ctk.CTkLabel(self.dp_value_row, text="", text_color=GRAY_400,
                                      font=self.fonts["body"])
        self.dp_suffix.pack(side="left", padx=8)
        self.dp_value_var.trace_add("write", lambda *_: self._recalc())

        disrow = ctk.CTkFrame(c, fg_color="transparent")
        self.disrow = disrow
        disrow.pack(fill="x", pady=4)
        ctk.CTkLabel(disrow, text="DISKON", text_color=GRAY_400,
                     font=self.fonts["label"], width=130, anchor="w").pack(side="left")
        self.diskon_var = tk.StringVar()
        ctk.CTkEntry(disrow, textvariable=self.diskon_var, width=140,
                     font=self.fonts["body"], height=32, placeholder_text="0").pack(side="left")
        ctk.CTkLabel(disrow, text="Rp", text_color=GRAY_400, font=self.fonts["body"]).pack(side="left", padx=8)
        self.diskon_var.trace_add("write", lambda *_: self._recalc())

        # --- Right column: Live Summary + actions ---
        self._build_summary(right)

    def _build_summary(self, parent):
        card = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=12,
                            border_width=1, border_color=GRAY_200)
        card.pack(fill="x")
        ctk.CTkLabel(card, text="Ringkasan", text_color=INK, font=self.fonts["h2"],
                     anchor="w").pack(fill="x", padx=16, pady=(14, 6))
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=(0, 14))

        self.sum_subtotal = tk.StringVar(value="Rp 0")
        self.sum_diskon = tk.StringVar(value="Rp 0")
        self.sum_dp = tk.StringVar(value="Rp 0")
        self.sum_sisa = tk.StringVar(value="Rp 0")
        self.sum_total = tk.StringVar(value="Rp 0")
        self.dp_caption = tk.StringVar(value="DP")

        def line(parent_, label_var_or_text, value_var, bold=False, color=GRAY_700):
            row = ctk.CTkFrame(parent_, fg_color="transparent")
            row.pack(fill="x", pady=2)
            fnt = self.fonts["body_b"] if bold else self.fonts["body"]
            if isinstance(label_var_or_text, str):
                ctk.CTkLabel(row, text=label_var_or_text, text_color=color,
                             font=fnt, anchor="w").pack(side="left")
            else:
                ctk.CTkLabel(row, textvariable=label_var_or_text, text_color=color,
                             font=fnt, anchor="w").pack(side="left")
            ctk.CTkLabel(row, textvariable=value_var, text_color=color, font=fnt,
                         anchor="e").pack(side="right")
            return row

        self.row_subtotal = line(inner, "Subtotal", self.sum_subtotal)
        self.row_diskon = line(inner, "Diskon", self.sum_diskon)
        self.row_dp = line(inner, self.dp_caption, self.sum_dp)
        self.row_sisa = line(inner, "Sisa Pembayaran", self.sum_sisa, bold=True, color=INK)

        total_box = ctk.CTkFrame(inner, fg_color=ORANGE_TINT, corner_radius=8)
        total_box.pack(fill="x", pady=(10, 0))
        self.total_box = total_box
        tb = ctk.CTkFrame(total_box, fg_color="transparent")
        tb.pack(fill="x", padx=12, pady=10)
        ctk.CTkLabel(tb, text="TOTAL", text_color=INK, font=self.fonts["label"]).pack(side="left")
        ctk.CTkLabel(tb, textvariable=self.sum_total, text_color=ORANGE_DARK,
                     font=self.fonts["total"]).pack(side="right")

        # actions
        actions = ctk.CTkFrame(parent, fg_color="transparent")
        actions.pack(fill="x", pady=(12, 0))
        self.generate_btn = ctk.CTkButton(
            actions, text="Generate PDF", height=46, font=self.fonts["h2"],
            fg_color=ORANGE, hover_color=ORANGE_DARK, text_color="white",
            command=self._generate,
        )
        self.generate_btn.pack(fill="x")
        ctk.CTkButton(
            actions, text="Buka Folder Output", height=36, font=self.fonts["body"],
            fg_color="#E9EBEF", text_color=INK, hover_color="#DCDFE5",
            command=self._open_output,
        ).pack(fill="x", pady=(8, 0))
        ctk.CTkButton(
            actions, text="Bersihkan", height=32, font=self.fonts["body"],
            fg_color="transparent", text_color=GRAY_400, border_width=1,
            border_color=GRAY_200, hover_color="#ECECEF", command=self._clear_form,
        ).pack(fill="x", pady=(8, 0))

    # ----- settings page ---------------------------------------------------- #
    def _build_settings_page(self, page):
        scroll = ctk.CTkScrollableFrame(page, fg_color="transparent")
        scroll.pack(fill="both", expand=True)
        self.s_entries = {}

        def entry_field(parent, label, key):
            row = self._labeled_row(parent, label)
            e = ctk.CTkEntry(row, font=self.fonts["body"], height=32)
            e.insert(0, str(self.settings.get(key, "")))
            e.pack(side="left", fill="x", expand=True)
            self.s_entries[key] = e
            return e

        c = self._make_card(scroll, "Perusahaan")
        entry_field(c, "NAMA", "company_name")
        entry_field(c, "TAGLINE", "company_tagline")
        entry_field(c, "ALAMAT 1", "company_address_line_1")
        entry_field(c, "ALAMAT 2", "company_address_line_2")
        entry_field(c, "NPWP (OPSIONAL)", "company_npwp")

        c = self._make_card(scroll, "Kontak")
        entry_field(c, "WHATSAPP", "company_phone")
        entry_field(c, "EMAIL", "company_email")
        entry_field(c, "INSTAGRAM", "company_instagram")

        c = self._make_card(scroll, "Bank")
        entry_field(c, "NAMA BANK", "bank_name")
        entry_field(c, "ATAS NAMA", "bank_account_name")
        entry_field(c, "NO. REKENING", "bank_account_number")

        c = self._make_card(scroll, "Catatan & Ketentuan")
        ctk.CTkLabel(c, text="CATATAN / TERMS", text_color=GRAY_400,
                     font=self.fonts["label"], anchor="w").pack(fill="x", pady=(4, 2))
        self.statement_box = ctk.CTkTextbox(c, height=80, font=self.fonts["body"])
        self.statement_box.pack(fill="x")
        self.statement_box.insert("1.0", self.settings.get("official_statement", ""))
        ctk.CTkLabel(c, text="DISCLAIMER PROFORMA", text_color=GRAY_400,
                     font=self.fonts["label"], anchor="w").pack(fill="x", pady=(10, 2))
        self.disclaimer_box = ctk.CTkTextbox(c, height=70, font=self.fonts["body"])
        self.disclaimer_box.pack(fill="x")
        self.disclaimer_box.insert("1.0", self.settings.get("proforma_disclaimer", ""))

        c = self._make_card(scroll, "Tanda Tangan")
        entry_field(c, "UCAPAN TERIMA KASIH", "thank_you_note")
        entry_field(c, "SALAM PENUTUP", "closing_text")
        entry_field(c, "NAMA TTD", "signature_name")

        c = self._make_card(scroll, "Opsi")
        trow = ctk.CTkFrame(c, fg_color="transparent")
        trow.pack(fill="x", pady=4)
        self.terbilang_switch = ctk.CTkSwitch(
            trow, text="Tampilkan Terbilang", font=self.fonts["body"],
            progress_color=ORANGE, text_color=INK)
        self.terbilang_switch.pack(side="left")
        if self.settings.get("show_terbilang", True):
            self.terbilang_switch.select()

        ctk.CTkButton(
            scroll, text="Simpan Pengaturan", height=44, font=self.fonts["h2"],
            fg_color=ORANGE, hover_color=ORANGE_DARK, text_color="white",
            command=self._save_settings,
        ).pack(fill="x", pady=(4, 12))

    # ----- history page ----------------------------------------------------- #
    def _build_history_page(self, page):
        head = ctk.CTkFrame(page, fg_color="transparent")
        head.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(head, text="Riwayat Invoice", text_color=INK,
                     font=self.fonts["h2"]).pack(side="left")
        ctk.CTkButton(
            head, text="＋ Invoice Baru", width=140, height=32,
            font=self.fonts["body_b"], fg_color=ORANGE, hover_color=ORANGE_DARK,
            text_color="white", command=self._new_invoice,
        ).pack(side="right")
        self.history_scroll = ctk.CTkScrollableFrame(page, fg_color="transparent")
        self.history_scroll.pack(fill="both", expand=True)

    def _refresh_history(self):
        for w in self.history_scroll.winfo_children():
            w.destroy()
        records = hm.load_invoices()
        if not records:
            ctk.CTkLabel(
                self.history_scroll, text="Belum ada invoice tersimpan.\n"
                "Invoice otomatis tersimpan di sini setiap kali kamu Generate PDF.",
                text_color=GRAY_400, font=self.fonts["body"], justify="left",
            ).pack(anchor="w", pady=30, padx=4)
            return
        for rec in records:
            self._history_card(rec)

    def _history_card(self, rec):
        card = ctk.CTkFrame(self.history_scroll, fg_color=CARD, corner_radius=10,
                            border_width=1, border_color=GRAY_200)
        card.pack(fill="x", pady=6)
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=10)

        info = ctk.CTkFrame(inner, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(info, text=rec.get("invoice_no", "-"), text_color=INK,
                     font=self.fonts["body_b"], anchor="w").pack(fill="x")
        sub = f"{rec.get('date', '')}   ·   {rec.get('bill_to', '')}"
        ctk.CTkLabel(info, text=sub, text_color=GRAY_400,
                     font=self.fonts["caption"], anchor="w").pack(fill="x")
        ctk.CTkLabel(info, text=rupiah(rec.get("total", 0)), text_color=ORANGE_DARK,
                     font=self.fonts["body_b"], anchor="w").pack(fill="x", pady=(2, 0))

        btns = ctk.CTkFrame(inner, fg_color="transparent")
        btns.pack(side="right")
        ctk.CTkButton(btns, text="Edit", width=60, height=30, font=self.fonts["body_b"],
                      fg_color=ORANGE, hover_color=ORANGE_DARK, text_color="white",
                      command=lambda r=rec: self._load_invoice(r)).pack(side="left", padx=4)
        if rec.get("pdf_path") and os.path.exists(rec["pdf_path"]):
            ctk.CTkButton(btns, text="Buka PDF", width=84, height=30,
                          font=self.fonts["body"], fg_color="#E9EBEF", text_color=INK,
                          hover_color="#DCDFE5",
                          command=lambda p=rec["pdf_path"]: self._open_file(p)
                          ).pack(side="left", padx=4)
        ctk.CTkButton(btns, text="Hapus", width=60, height=30, font=self.fonts["body"],
                      fg_color="transparent", text_color=DANGER, border_width=1,
                      border_color=GRAY_200, hover_color="#F3D6D6",
                      command=lambda r=rec: self._delete_invoice(r)).pack(side="left", padx=4)

    def _load_invoice(self, rec):
        self._invoice_no_touched = True
        self.invoice_no_var.set(rec.get("invoice_no", ""))
        try:
            self.date_picker.set_date(datetime.date.fromisoformat(rec.get("date_iso", "")))
        except (ValueError, TypeError):
            pass
        self.bill_to_var.set(rec.get("bill_to", ""))

        for r in list(self.item_rows):
            r.destroy()
        self.item_rows.clear()
        for it in (rec.get("items") or [{}]):
            self._add_item_row()
            row = self.item_rows[-1]
            row.desc_var.set(it.get("description", ""))
            row.qty_var.set(str(it.get("qty", 1)))
            amt = it.get("amount", 0)
            row.amt_var.set(str(int(amt)) if amt else "")
            row._fmt_amount()
        self._sync_remove_buttons()

        dp_type = rec.get("dp_type", "No DP")
        seg = {"No DP": "Tanpa DP", "Percentage": "Persentase",
               "Fixed Amount": "Nominal"}.get(dp_type, "Tanpa DP")
        self.dp_var.set(seg)
        self._on_dp_change(seg)
        if dp_type == "Percentage":
            pct = rec.get("dp_percentage", 0) or 0
            self.dp_value_var.set(str(int(pct) if float(pct) == int(pct) else pct))
        elif dp_type == "Fixed Amount":
            self.dp_value_var.set(str(int(rec.get("dp_amount", 0) or 0)))
        else:
            self.dp_value_var.set("")

        dk = rec.get("diskon", 0)
        self.diskon_var.set(str(int(dk)) if dk else "")

        self._editing_id = rec.get("id")
        self._update_edit_banner()
        self._recalc()
        self._show_page("Create Invoice")
        self._toast("Invoice dibuka untuk diedit", OK)

    def _delete_invoice(self, rec):
        if not messagebox.askyesno("Hapus Invoice",
                                   f"Hapus invoice {rec.get('invoice_no', '')} dari riwayat?"):
            return
        hm.delete_invoice(rec.get("id"))
        if self._editing_id == rec.get("id"):
            self._editing_id = None
            self._update_edit_banner()
        self._refresh_history()
        self._toast("Invoice dihapus", OK)

    def _new_invoice(self):
        self._editing_id = None
        self._clear_form()
        self._show_page("Create Invoice")

    def _update_edit_banner(self):
        if getattr(self, "_editing_id", None):
            self.edit_status.configure(
                text="✎ Sedang mengedit invoice tersimpan — klik “Bersihkan” untuk invoice baru.")
        else:
            self.edit_status.configure(text="")

    def _open_file(self, path):
        if sys.platform.startswith("win"):
            os.startfile(path)  # noqa: SLF001
        elif sys.platform == "darwin":
            subprocess.run(["open", path], check=False)
        else:
            subprocess.run(["xdg-open", path], check=False)

    # ----- item rows -------------------------------------------------------- #
    def _add_item_row(self):
        row = ItemRow(self.items_container, self._remove_item_row, self._recalc, self.fonts)
        self.item_rows.append(row)
        self._sync_remove_buttons()
        row.description.focus_set()
        self._recalc()

    def _remove_item_row(self, row):
        if len(self.item_rows) <= 1:
            return
        row.destroy()
        self.item_rows.remove(row)
        self._sync_remove_buttons()
        self._recalc()

    def _sync_remove_buttons(self):
        only_one = len(self.item_rows) == 1
        for r in self.item_rows:
            r.show_remove(not only_one)

    # ----- DP --------------------------------------------------------------- #
    def _on_dp_change(self, value):
        if value == "Tanpa DP":
            self.dp_value_row.pack_forget()
        else:
            self.dp_suffix.configure(text="%" if value == "Persentase" else "Rp")
            self.dp_value_row.pack(fill="x", pady=4, before=self.disrow)
        self._recalc()

    def _dp_internal(self):
        return DP_MAP.get(self.dp_var.get(), "No DP")

    # ----- live recompute --------------------------------------------------- #
    def _gather_items(self):
        return [r.values() for r in self.item_rows if not r.is_blank()]

    def _current_totals(self):
        dp_type = self._dp_internal()
        pct = to_pct(self.dp_value_var.get()) if dp_type == "Percentage" else 0
        amt = to_number(self.dp_value_var.get()) if dp_type == "Fixed Amount" else 0
        return compute_totals(self._gather_items(), dp_type, pct, amt,
                              to_number(self.diskon_var.get()))

    def _recalc(self, *_):
        t = self._current_totals()
        self.sum_subtotal.set(rupiah(t["subtotal"]))
        self.sum_total.set(rupiah(t["total"]))

        # Re-pack conditional rows in a stable order, always above the TOTAL box.
        for r in (self.row_diskon, self.row_dp, self.row_sisa):
            r.pack_forget()
        if t["diskon"] > 0:
            self.sum_diskon.set("− " + rupiah(t["diskon"]))
            self.row_diskon.pack(fill="x", pady=2, before=self.total_box)
        if t["show_sisa"]:
            self.dp_caption.set(t["dp_label"] or "DP")
            self.sum_dp.set("− " + rupiah(t["dp_amount"]))
            self.sum_sisa.set(rupiah(t["sisa"]))
            self.row_dp.pack(fill="x", pady=2, before=self.total_box)
            self.row_sisa.pack(fill="x", pady=2, before=self.total_box)

        ready = bool(self.bill_to_var.get().strip()) and t["subtotal"] > 0
        self.generate_btn.configure(
            state="normal" if ready else "disabled",
            fg_color=ORANGE if ready else "#D7DAE0",
            text_color="white" if ready else GRAY_400,
        )

    def _refresh_invoice_no(self):
        # No. Proforma is manual now: only prefill a date-based suggestion while
        # the user hasn't typed their own number yet.
        if getattr(self, "_invoice_no_touched", False):
            return
        self.invoice_no_var.set(sm.peek_next_invoice_no(self.settings, self._picked_date()))

    def _picked_date(self):
        try:
            return self.date_picker.get_date()
        except Exception:
            return datetime.date.today()

    # ----- settings save ---------------------------------------------------- #
    def _save_settings(self):
        for key, entry in self.s_entries.items():
            self.settings[key] = entry.get().strip()
        self.settings["official_statement"] = self.statement_box.get("1.0", "end").strip()
        self.settings["proforma_disclaimer"] = self.disclaimer_box.get("1.0", "end").strip()
        self.settings["show_terbilang"] = bool(self.terbilang_switch.get())
        sm.save_settings(self.settings)
        self._refresh_invoice_no()
        self._toast("Pengaturan tersimpan", OK)

    # ----- generate --------------------------------------------------------- #
    def _validate(self):
        if not self.bill_to_var.get().strip():
            return None, "Nama klien (Kepada Yth.) wajib diisi."
        items = []
        for i, r in enumerate(self.item_rows, start=1):
            if r.is_blank():
                continue
            v = r.values()
            if not v["description"]:
                return None, f"Item {i}: deskripsi wajib diisi."
            if v["qty"] <= 0:
                return None, f"Item {i}: Qty harus lebih dari 0."
            if v["amount"] <= 0:
                return None, f"Item {i}: Jumlah harus lebih dari 0."
            items.append(v)
        if not items:
            return None, "Minimal satu item dengan jumlah harus diisi."

        dp_type = self._dp_internal()
        t = self._current_totals()
        if dp_type == "Percentage" and to_pct(self.dp_value_var.get()) <= 0:
            return None, "Persentase DP harus lebih dari 0."
        if dp_type == "Fixed Amount":
            if to_number(self.dp_value_var.get()) <= 0:
                return None, "Nominal DP harus lebih dari 0."
            if t["dp_amount"] > t["total"]:
                return None, "Nominal DP melebihi total."
        if not self.settings.get("bank_account_number"):
            return None, "Data bank kosong. Isi dulu di tab Settings."
        if not self.settings.get("signature_name"):
            return None, "Nama tanda tangan kosong. Isi dulu di tab Settings."

        if not self.invoice_no_var.get().strip():
            return None, "No. Proforma wajib diisi."

        data = {
            "invoice_no": self.invoice_no_var.get().strip(),
            "date": format_date_indonesian(self._picked_date()),
            "bill_to": self.bill_to_var.get().strip(),
            "items": items,
            "dp_type": dp_type,
            "dp_percentage": to_pct(self.dp_value_var.get()) if dp_type == "Percentage" else 0,
            "dp_amount": to_number(self.dp_value_var.get()) if dp_type == "Fixed Amount" else 0,
            "diskon": to_number(self.diskon_var.get()),
        }
        return data, None

    def _generate(self):
        data, error = self._validate()
        if error:
            messagebox.showerror("Periksa kembali", error)
            return

        self.settings = sm.load_settings()
        invoice_no = data["invoice_no"]  # manual, entered by the user

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        save_path = filedialog.asksaveasfilename(
            title="Simpan Invoice PDF", initialdir=OUTPUT_DIR,
            initialfile=suggest_filename(invoice_no, data["bill_to"]),
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if not save_path:
            return

        try:
            path = generate_invoice_pdf(data, self.settings, invoice_no, output_path=save_path)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Gagal", f"Gagal menyimpan PDF:\n{e}")
            return

        self._save_to_history(data, path)
        self._toast("Invoice tersimpan", OK)
        self._open_folder(os.path.dirname(path))

    def _save_to_history(self, data, pdf_path):
        record = {
            "id": self._editing_id or datetime.datetime.now().strftime("%Y%m%d%H%M%S%f"),
            "invoice_no": data["invoice_no"],
            "date": data["date"],
            "date_iso": self._picked_date().isoformat(),
            "bill_to": data["bill_to"],
            "items": data["items"],
            "dp_type": data["dp_type"],
            "dp_percentage": data["dp_percentage"],
            "dp_amount": data["dp_amount"],
            "diskon": data["diskon"],
            "total": self._current_totals()["total"],
            "pdf_path": pdf_path,
            "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        hm.upsert_invoice(record)
        self._editing_id = record["id"]
        self._update_edit_banner()

    def _clear_form(self):
        self.bill_to_var.set("")
        self.diskon_var.set("")
        for r in list(self.item_rows):
            r.destroy()
        self.item_rows.clear()
        self.dp_var.set("Tanpa DP")
        self._on_dp_change("Tanpa DP")
        self.dp_value_var.set("")
        self.date_picker.set_date(datetime.date.today())
        self._invoice_no_touched = False
        self._editing_id = None
        self._update_edit_banner()
        self._add_item_row()
        self._refresh_invoice_no()
        self._recalc()

    # ----- misc ------------------------------------------------------------- #
    def _toast(self, message, color=OK):
        try:
            tp = ctk.CTkToplevel(self)
            tp.overrideredirect(True)
            tp.attributes("-topmost", True)
            self.update_idletasks()
            x = self.winfo_rootx() + self.winfo_width() - 250
            y = self.winfo_rooty() + self.winfo_height() - 90
            tp.geometry(f"230x44+{x}+{y}")
            frame = ctk.CTkFrame(tp, fg_color=color, corner_radius=8)
            frame.pack(fill="both", expand=True)
            ctk.CTkLabel(frame, text="✓  " + message, text_color="white",
                         font=self.fonts["body_b"]).pack(expand=True)
            tp.after(2400, tp.destroy)
        except Exception:
            pass

    def _open_output(self):
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        self._open_folder(OUTPUT_DIR)

    def _open_folder(self, folder):
        if sys.platform.startswith("win"):
            os.startfile(folder)  # noqa: SLF001
        elif sys.platform == "darwin":
            subprocess.run(["open", folder], check=False)
        else:
            subprocess.run(["xdg-open", folder], check=False)


if __name__ == "__main__":
    app = InvoiceApp()
    app.mainloop()
