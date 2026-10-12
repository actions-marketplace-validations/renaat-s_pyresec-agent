"""Central audit log for every email PYRESEC sends via Resend."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

AUDIT_FILE = Path("scripts/.email_audit.json")


def log_email(to: str, subject: str, source: str, status: str, error: str = ""):
    """Append one email-send record to the audit log.

    Args:
        to: recipient address
        subject: email subject line
        source: e.g. "git_scraper", "notify.intake", "notify.alert"
        status: "success" or "failed"
        error: optional error message
    """
    entries = []
    if AUDIT_FILE.exists():
        try:
            with AUDIT_FILE.open("r", encoding="utf-8") as f:
                entries = json.load(f)
        except Exception:
            entries = []

    entries.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "to": to,
        "subject": subject,
        "source": source,
        "status": status,
        "error": error,
    })

    # Keep last 50,000 entries to avoid unbounded growth
    entries = entries[-50000:]
    try:
        with AUDIT_FILE.open("w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def count_sent() -> int:
    """Total successful sends recorded in the audit log."""
    if not AUDIT_FILE.exists():
        return 0
    try:
        with AUDIT_FILE.open("r", encoding="utf-8") as f:
            entries = json.load(f)
        return sum(1 for e in entries if e.get("status") == "success")
    except Exception:
        return 0
