"""Simple Pro Forma Invoice Generator - CustomTkinter GUI.

Two tabs:
  - Create Invoice: fill the form, click Generate PDF.
  - Settings: company / bank / signature defaults saved to settings.json.
"""

import datetime
import os
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

import settings_manager as sm
from pdf_generator import OUTPUT_DIR, generate_invoice_pdf

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

DP_OPTIONS = ["No DP", "Percentage", "Fixed Amount"]


class ItemRow:
    """One editable item row (Description / Qty / Amount + remove button)."""

    def __init__(self, parent, on_remove):
        self.frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.frame.pack(fill="x", pady=3)
        self.on_remove = on_remove

        self.description = ctk.CTkEntry(self.frame, placeholder_text="Description")
        self.description.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.qty = ctk.CTkEntry(self.frame, width=60, placeholder_text="Qty")
        self.qty.insert(0, "1")
        self.qty.pack(side="left", padx=(0, 6))

        self.amount = ctk.CTkEntry(self.frame, width=120, placeholder_text="Amount")
        self.amount.pack(side="left", padx=(0, 6))

        self.remove_btn = ctk.CTkButton(
            self.frame, text="✕", width=32, fg_color="#c0392b",
            hover_color="#a93226", command=self._remove,
        )
        self.remove_btn.pack(side="left")

    def _remove(self):
        self.on_remove(self)

    def destroy(self):
        self.frame.destroy()

    def get(self):
        return {
            "description": self.description.get().strip(),
            "qty": self.qty.get().strip(),
            "amount": self.amount.get().strip(),
        }


class InvoiceApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Pro Forma Invoice Generator")
        self.geometry("780x760")
        self.minsize(720, 640)

        self.settings = sm.load_settings()
        self.item_rows = []

        self.tabs = ctk.CTkTabview(self)
        self.tabs.pack(fill="both", expand=True, padx=12, pady=12)
        self.tabs.add("Create Invoice")
        self.tabs.add("Settings")

        self._build_invoice_tab(self.tabs.tab("Create Invoice"))
        self._build_settings_tab(self.tabs.tab("Settings"))

        self._add_item_row()  # start with one row
        self._refresh_invoice_no()

    # ------------------------------------------------------------------ #
    # Create Invoice tab
    # ------------------------------------------------------------------ #
    def _build_invoice_tab(self, tab):
        scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        # Header section
        header = ctk.CTkFrame(scroll)
        header.pack(fill="x", pady=(0, 10))

        row = ctk.CTkFrame(header, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=(10, 4))
        ctk.CTkLabel(row, text="Invoice No (auto):", width=130, anchor="w").pack(side="left")
        self.invoice_no_var = tk.StringVar(value="-")
        ctk.CTkLabel(
            row, textvariable=self.invoice_no_var, anchor="w",
            font=ctk.CTkFont(weight="bold"),
        ).pack(side="left")

        row = ctk.CTkFrame(header, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=4)
        ctk.CTkLabel(row, text="Date:", width=130, anchor="w").pack(side="left")
        self.date_entry = ctk.CTkEntry(row, placeholder_text="e.g. 7 Juni 2026")
        self.date_entry.pack(side="left", fill="x", expand=True)
        self.date_entry.insert(0, _today_indonesian())

        row = ctk.CTkFrame(header, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=(4, 10))
        ctk.CTkLabel(row, text="Bill to:", width=130, anchor="w").pack(side="left")
        self.bill_to_entry = ctk.CTkEntry(row, placeholder_text="Customer name")
        self.bill_to_entry.pack(side="left", fill="x", expand=True)

        # Items section
        items_box = ctk.CTkFrame(scroll)
        items_box.pack(fill="x", pady=(0, 10))
        head = ctk.CTkFrame(items_box, fg_color="transparent")
        head.pack(fill="x", padx=10, pady=(10, 0))
        ctk.CTkLabel(head, text="Items", font=ctk.CTkFont(size=15, weight="bold")).pack(side="left")
        ctk.CTkButton(head, text="+ Add Item", width=100, command=self._add_item_row).pack(side="right")

        self.items_container = ctk.CTkFrame(items_box, fg_color="transparent")
        self.items_container.pack(fill="x", padx=10, pady=10)

        # DP section
        dp_box = ctk.CTkFrame(scroll)
        dp_box.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(
            dp_box, text="Down Payment (DP)",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(anchor="w", padx=10, pady=(10, 4))

        row = ctk.CTkFrame(dp_box, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=4)
        ctk.CTkLabel(row, text="DP Type:", width=130, anchor="w").pack(side="left")
        self.dp_type_var = tk.StringVar(value="No DP")
        ctk.CTkOptionMenu(
            row, values=DP_OPTIONS, variable=self.dp_type_var,
            command=self._on_dp_type_change,
        ).pack(side="left")

        self.dp_pct_row = ctk.CTkFrame(dp_box, fg_color="transparent")
        ctk.CTkLabel(self.dp_pct_row, text="DP Percentage:", width=130, anchor="w").pack(side="left")
        self.dp_pct_entry = ctk.CTkEntry(self.dp_pct_row, width=120, placeholder_text="e.g. 50")
        self.dp_pct_entry.pack(side="left")

        self.dp_amt_row = ctk.CTkFrame(dp_box, fg_color="transparent")
        ctk.CTkLabel(self.dp_amt_row, text="DP Amount:", width=130, anchor="w").pack(side="left")
        self.dp_amt_entry = ctk.CTkEntry(self.dp_amt_row, width=120, placeholder_text="e.g. 750000")
        self.dp_amt_entry.pack(side="left")
        # padding row at bottom
        ctk.CTkFrame(dp_box, fg_color="transparent", height=6).pack()

        # Buttons
        btns = ctk.CTkFrame(scroll, fg_color="transparent")
        btns.pack(fill="x", pady=(4, 10))
        ctk.CTkButton(
            btns, text="Generate PDF", height=42,
            font=ctk.CTkFont(size=15, weight="bold"),
            command=self._generate,
        ).pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkButton(
            btns, text="Clear Form", height=42, fg_color="gray40",
            hover_color="gray30", command=self._clear_form,
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            btns, text="Open Output Folder", height=42, fg_color="gray40",
            hover_color="gray30", command=self._open_output,
        ).pack(side="left")

    def _add_item_row(self):
        row = ItemRow(self.items_container, self._remove_item_row)
        self.item_rows.append(row)

    def _remove_item_row(self, row):
        if len(self.item_rows) <= 1:
            messagebox.showinfo("Info", "At least one item is required.")
            return
        row.destroy()
        self.item_rows.remove(row)

    def _on_dp_type_change(self, value):
        self.dp_pct_row.pack_forget()
        self.dp_amt_row.pack_forget()
        if value == "Percentage":
            self.dp_pct_row.pack(fill="x", padx=10, pady=4)
        elif value == "Fixed Amount":
            self.dp_amt_row.pack(fill="x", padx=10, pady=4)

    def _refresh_invoice_no(self):
        today = datetime.date.today()
        self.invoice_no_var.set(sm.peek_next_invoice_no(self.settings, today))

    # ------------------------------------------------------------------ #
    # Settings tab
    # ------------------------------------------------------------------ #
    def _build_settings_tab(self, tab):
        scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        scroll.pack(fill="both", expand=True)
        self.settings_entries = {}

        def add_entry(parent, label, key, width=380):
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", pady=4)
            ctk.CTkLabel(row, text=label, width=160, anchor="w").pack(side="left")
            entry = ctk.CTkEntry(row, width=width)
            entry.pack(side="left", fill="x", expand=True)
            entry.insert(0, str(self.settings.get(key, "")))
            self.settings_entries[key] = entry
            return entry

        # Company
        sec = ctk.CTkFrame(scroll)
        sec.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(sec, text="Company", font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", padx=10, pady=(10, 4))
        inner = ctk.CTkFrame(sec, fg_color="transparent")
        inner.pack(fill="x", padx=10, pady=(0, 10))
        add_entry(inner, "Company Name", "company_name")
        add_entry(inner, "Address Line 1", "company_address_line_1")
        add_entry(inner, "Address Line 2", "company_address_line_2")

        logo_row = ctk.CTkFrame(inner, fg_color="transparent")
        logo_row.pack(fill="x", pady=4)
        ctk.CTkLabel(logo_row, text="Logo Path", width=160, anchor="w").pack(side="left")
        self.logo_entry = ctk.CTkEntry(logo_row)
        self.logo_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.logo_entry.insert(0, str(self.settings.get("logo_path", "")))
        self.settings_entries["logo_path"] = self.logo_entry
        ctk.CTkButton(logo_row, text="Browse", width=80, command=self._browse_logo).pack(side="left")

        # Bank
        sec = ctk.CTkFrame(scroll)
        sec.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(sec, text="Default Bank", font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", padx=10, pady=(10, 4))
        inner = ctk.CTkFrame(sec, fg_color="transparent")
        inner.pack(fill="x", padx=10, pady=(0, 10))
        add_entry(inner, "Bank Name", "bank_name")
        add_entry(inner, "Bank Account Name", "bank_account_name")
        add_entry(inner, "Bank Account Number", "bank_account_number")

        # Statement
        sec = ctk.CTkFrame(scroll)
        sec.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(sec, text="Official Statement", font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", padx=10, pady=(10, 4))
        self.statement_box = ctk.CTkTextbox(sec, height=90)
        self.statement_box.pack(fill="x", padx=10, pady=(0, 10))
        self.statement_box.insert("1.0", self.settings.get("official_statement", ""))

        # Signature
        sec = ctk.CTkFrame(scroll)
        sec.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(sec, text="Signature", font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", padx=10, pady=(10, 4))
        inner = ctk.CTkFrame(sec, fg_color="transparent")
        inner.pack(fill="x", padx=10, pady=(0, 10))
        add_entry(inner, "Closing Text", "closing_text")
        add_entry(inner, "Signature Name", "signature_name")

        ctk.CTkButton(
            scroll, text="Save Settings", height=42,
            font=ctk.CTkFont(size=15, weight="bold"),
            command=self._save_settings,
        ).pack(fill="x", pady=(4, 10))

    def _browse_logo(self):
        path = filedialog.askopenfilename(
            title="Select Logo",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.gif"), ("All files", "*.*")],
        )
        if path:
            self.logo_entry.delete(0, "end")
            self.logo_entry.insert(0, path)

    def _save_settings(self):
        for key, entry in self.settings_entries.items():
            self.settings[key] = entry.get().strip()
        self.settings["official_statement"] = self.statement_box.get("1.0", "end").strip()
        sm.save_settings(self.settings)
        messagebox.showinfo("Saved", "Settings saved successfully.")

    # ------------------------------------------------------------------ #
    # Generate
    # ------------------------------------------------------------------ #
    def _collect_and_validate(self):
        date = self.date_entry.get().strip()
        bill_to = self.bill_to_entry.get().strip()
        if not date:
            return None, "Date is required."
        if not bill_to:
            return None, "Bill to is required."

        items = []
        for i, row in enumerate(self.item_rows, start=1):
            raw = row.get()
            if not raw["description"]:
                return None, f"Item {i}: description is required."
            try:
                qty = float(raw["qty"])
            except ValueError:
                return None, f"Item {i}: Qty must be a number."
            if qty <= 0:
                return None, f"Item {i}: Qty must be greater than 0."
            try:
                amount = float(raw["amount"])
            except ValueError:
                return None, f"Item {i}: Amount must be a number."
            if amount <= 0:
                return None, f"Item {i}: Amount must be greater than 0."
            items.append({
                "description": raw["description"],
                "qty": int(qty) if qty == int(qty) else qty,
                "amount": amount,
            })

        if not items:
            return None, "At least one item is required."

        dp_type = self.dp_type_var.get()
        dp_percentage = 0
        dp_amount = 0
        if dp_type == "Percentage":
            try:
                dp_percentage = float(self.dp_pct_entry.get())
            except ValueError:
                return None, "DP Percentage must be a number."
            if dp_percentage <= 0:
                return None, "DP Percentage must be greater than 0."
        elif dp_type == "Fixed Amount":
            try:
                dp_amount = float(self.dp_amt_entry.get())
            except ValueError:
                return None, "DP Amount must be a number."
            if dp_amount <= 0:
                return None, "DP Amount must be greater than 0."

        # bank / signature come from settings; make sure they're set
        if not self.settings.get("bank_account_number"):
            return None, "Bank details are empty. Fill them in Settings first."
        if not self.settings.get("signature_name"):
            return None, "Signature name is empty. Fill it in Settings first."

        data = {
            "date": date,
            "bill_to": bill_to,
            "items": items,
            "dp_type": dp_type,
            "dp_percentage": dp_percentage,
            "dp_amount": dp_amount,
        }
        return data, None

    def _generate(self):
        data, error = self._collect_and_validate()
        if error:
            messagebox.showerror("Validation Error", error)
            return

        today = datetime.date.today()
        # Reload settings so the latest saved values + counter are used.
        self.settings = sm.load_settings()
        invoice_no = sm.peek_next_invoice_no(self.settings, today)
        try:
            path = generate_invoice_pdf(data, self.settings, invoice_no)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Error", f"Failed to generate PDF:\n{e}")
            return

        # Only after success: commit the counter.
        sm.commit_invoice_no(self.settings, today)
        self._refresh_invoice_no()

        if messagebox.askyesno(
            "Success",
            f"PDF generated:\n{os.path.basename(path)}\n\nOpen the output folder?",
        ):
            self._open_output()

    def _clear_form(self):
        self.bill_to_entry.delete(0, "end")
        for row in list(self.item_rows):
            row.destroy()
        self.item_rows.clear()
        self._add_item_row()
        self.dp_type_var.set("No DP")
        self._on_dp_type_change("No DP")
        self.dp_pct_entry.delete(0, "end")
        self.dp_amt_entry.delete(0, "end")

    def _open_output(self):
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        if sys.platform.startswith("win"):
            os.startfile(OUTPUT_DIR)  # noqa: SLF001
        elif sys.platform == "darwin":
            subprocess.run(["open", OUTPUT_DIR], check=False)
        else:
            subprocess.run(["xdg-open", OUTPUT_DIR], check=False)


def _today_indonesian():
    months = [
        "", "Januari", "Februari", "Maret", "April", "Mei", "Juni",
        "Juli", "Agustus", "September", "Oktober", "November", "Desember",
    ]
    t = datetime.date.today()
    return f"{t.day} {months[t.month]} {t.year}"


if __name__ == "__main__":
    app = InvoiceApp()
    app.mainloop()
