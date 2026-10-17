"""PYRESEC Cloud Store — durable shared pipeline state in GCS.

Cloud Run container filesystems are ephemeral, and the local outreach
engines run on a different machine. Both sides therefore read/write one
JSON document in GCS:

    {"suppressions": [...], "paid": [...]}

  suppressions : Resend webhook events (bounced/complained/clicked) that
                 must stop the follow-up sequence for an email address.
  paid         : Stripe closed_won refs mirrored from stripe_webhook so
                 the local follow-up engine can see production payments.

Config: env SUPPRESSION_STORE=gs://<bucket>/<path>.json
Auth on Cloud Run: default service account via ADC (no keys in code).
"""

import json
import os
from datetime import datetime, timezone

_DEFAULT = {"suppressions": [], "paid": []}


def store_path() -> str:
    return os.getenv("SUPPRESSION_STORE", "").strip()


def configured() -> bool:
    return store_path().startswith("gs://")


def _blob():
    if not configured():
        raise RuntimeError("SUPPRESSION_STORE not configured (gs://...)")
    from google.cloud import storage  # lazy — only needed server-side
    raw = store_path()[len("gs://"):]
    bucket_name, _, blob_name = raw.partition("/")
    if not bucket_name or not blob_name:
        raise RuntimeError(f"malformed SUPPRESSION_STORE: {store_path()}")
    client = storage.Client()
    return client.bucket(bucket_name).blob(blob_name)


def load() -> dict:
    """Read the store; missing file -> defaults (never raises for 404)."""
    if not configured():
        return json.loads(json.dumps(_DEFAULT))
    try:
        blob = _blob()
        if not blob.exists():
            return json.loads(json.dumps(_DEFAULT))
        data = json.loads(blob.download_as_text(encoding="utf-8"))
        data.setdefault("suppressions", [])
        data.setdefault("paid", [])
        return data
    except Exception:
        # Fail open for readers; writers re-raise via save().
        return json.loads(json.dumps(_DEFAULT))


def save(data: dict) -> None:
    blob = _blob()
    data.setdefault("suppressions", [])
    data.setdefault("paid", [])
    blob.upload_from_string(json.dumps(data, indent=2, ensure_ascii=False),
                            content_type="application/json")


def add_suppression(email: str, reason: str, note: str = "") -> dict | None:
    """Idempotent by (email, reason) — Stripe/Resend retry deliveries."""
    email = (email or "").strip().lower()
    if not email:
        return None
    data = load()
    for item in data["suppressions"]:
        if item.get("email") == email and item.get("reason") == reason:
            return None
    entry = {
        "email": email,
        "reason": reason,
        "ts": datetime.now(timezone.utc).isoformat(),
        "note": note,
    }
    data["suppressions"].append(entry)
    save(data)
    return entry


def add_paid(ref: str, lead: str, model: str, amount: float = 0.0) -> dict | None:
    """Mirror a closed_won payment so local engines can see it. Idempotent by ref."""
    ref = (ref or "").strip()
    if not ref:
        return None
    data = load()
    for item in data["paid"]:
        if item.get("ref") == ref:
            return None
    entry = {
        "ref": ref,
        "lead": (lead or "").strip().lower(),
        "model": model,
        "amount": float(amount),
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    data["paid"].append(entry)
    save(data)
    return entry


if __name__ == "__main__":
    if not configured():
        print("SUPPRESSION_STORE not configured — set gs://<bucket>/<file>.json")
    else:
        print(json.dumps(load(), indent=2))
