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

Auth: no SDK, no keys in code.
  on Cloud Run : metadata-server access token of the default service
                 account (ADC equivalent), refreshed per call.
  elsewhere    : gcloud Application Default Credentials are NOT used —
                 local engines read via GET /v1/pipeline/state instead.
"""

import json
import os
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

_DEFAULT = {"suppressions": [], "paid": []}
_METADATA = "http://metadata.google.internal/computeMetadata/v1"
_TOKEN_URL = f"{_METADATA}/instance/service-accounts/default/token"


def store_path() -> str:
    return os.getenv("SUPPRESSION_STORE", "").strip()


def configured() -> bool:
    return store_path().startswith("gs://")


def _parse_store() -> tuple[str, str]:
    if not configured():
        raise RuntimeError("SUPPRESSION_STORE not configured (gs://...)")
    raw = store_path()[len("gs://"):]
    bucket_name, _, blob_name = raw.partition("/")
    if not bucket_name or not blob_name:
        raise RuntimeError(f"malformed SUPPRESSION_STORE: {store_path()}")
    return bucket_name, blob_name


def _access_token() -> str:
    """Token from the Cloud Run metadata server (works only on GCP)."""
    r = httpx.get(_TOKEN_URL, headers={"Metadata-Flavor": "Google"}, timeout=3.0)
    r.raise_for_status()
    return r.json()["access_token"]


def _request(method: str, params: str = "", data: bytes | None = None,
             content_type: str = "application/json") -> httpx.Response:
    bucket, blob = _parse_store()
    if method == "POST":  # simple upload endpoint, not the resource path
        url = (f"https://storage.googleapis.com/upload/storage/v1/b/{bucket}/o"
               f"?uploadType=media&name={quote(blob, safe='')}")
    else:
        url = (f"https://storage.googleapis.com/storage/v1/b/{bucket}/o/"
               f"{quote(blob, safe='')}{params}")
    headers = {"Authorization": f"Bearer {_access_token()}"}
    kwargs = {"headers": headers, "timeout": 10.0}
    if data is not None:
        kwargs["content"] = data
        kwargs["headers"] = {**headers, "Content-Type": content_type}
    return httpx.request(method, url, **kwargs)


def load() -> dict:
    """Read the store; missing file -> defaults (never raises for readers)."""
    if not configured():
        return json.loads(json.dumps(_DEFAULT))
    try:
        resp = _request("GET", params="?alt=media")
        if resp.status_code == 404:
            return json.loads(json.dumps(_DEFAULT))
        resp.raise_for_status()
        data = resp.json()
        data.setdefault("suppressions", [])
        data.setdefault("paid", [])
        return data
    except Exception:
        return json.loads(json.dumps(_DEFAULT))


def save(data: dict) -> None:
    data.setdefault("suppressions", [])
    data.setdefault("paid", [])
    payload = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
    resp = _request("POST", data=payload)
    resp.raise_for_status()


def add_suppression(email: str, reason: str, note: str = "") -> dict | None:
    """Idempotent by (email, reason) — Resend retries deliveries."""
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
