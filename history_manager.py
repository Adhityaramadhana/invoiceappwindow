"""Local invoice history — stores generated invoices in invoices.json so they
can be listed, re-opened, edited, and regenerated."""

import json
import os

from settings_manager import app_dir

INVOICES_PATH = os.path.join(app_dir(), "invoices.json")


def load_invoices():
    """Return the list of saved invoice records (newest first)."""
    if not os.path.exists(INVOICES_PATH):
        return []
    try:
        with open(INVOICES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_invoices(records):
    with open(INVOICES_PATH, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)


def upsert_invoice(record):
    """Insert a new record (newest first) or update an existing one by id."""
    records = load_invoices()
    for i, r in enumerate(records):
        if r.get("id") == record.get("id"):
            records[i] = record
            break
    else:
        records.insert(0, record)
    save_invoices(records)
    return records


def delete_invoice(record_id):
    records = [r for r in load_invoices() if r.get("id") != record_id]
    save_invoices(records)
    return records
