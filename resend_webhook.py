"""PYRESEC Resend webhook -> follow-up suppression.

Resend signs deliveries with the svix scheme (same as Stripe/Clerk):
  headers : svix-id, svix-timestamp, svix-signature ("v1,<base64> ...")
  signed  : "{svix-id}.{svix_timestamp}.{raw_body}"  HMAC-SHA256(secret)

Handled events (everything else is ignored):
  email.bounced     mailbox rejected it      -> stop following up
  email.complained  spam complaint           -> stop following up (legal)
  email.clicked     they clicked a link      -> engaged; reply/email is the
                                                right channel now, not nudges

NOT handled (Resend limitation): plain replies. Inbound email needs a
receiving domain; until then replies land in the mailbox/Resend dashboard
and are actioned manually (Telegram approval daemon covers new leads).

Storage: cloud_store (GCS) when SUPPRESSION_STORE is set; otherwise the
write is a no-op with status "store_unconfigured" (dev/test).
"""

import base64
import hashlib
import hmac
import json
import time

import cloud_store

SUPPRESS_EVENTS = {
    "email.bounced": "bounced",
    "email.complained": "complained",
    "email.clicked": "clicked",
}


def verify_signature(body: bytes, headers: dict, secret: str,
                     now: float = None, tolerance: int = 300) -> bool:
    """svix signature check. headers may be a case-insensitive mapping."""
    ts = _header(headers, "svix-timestamp")
    sig_header = _header(headers, "svix-signature")
    if not ts or not sig_header:
        return False
    try:
        ts_i = int(ts)
    except ValueError:
        return False
    if now is None:
        now = time.time()
    if abs(now - ts_i) > tolerance:
        return False

    signed = f"{_header(headers, 'svix-id')}.{ts}.{body.decode('utf-8', errors='replace')}"
    mac = hmac.new(secret.encode("utf-8"), signed.encode("utf-8"), hashlib.sha256)
    expected = base64.b64encode(mac.digest()).decode("ascii")

    for part in sig_header.split():
        version, _, value = part.partition(",")
        if version == "v1" and hmac.compare_digest(value, expected):
            return True
    return False


def _header(headers: dict, name: str) -> str:
    if hasattr(headers, "get"):
        val = headers.get(name) or headers.get(name.lower()) or ""
        if val:
            return val
    # plain dict fallback, case-insensitive
    for k, v in (headers or {}).items():
        if k.lower() == name.lower():
            return str(v)
    return ""


def _recipients(payload: dict) -> list[str]:
    """Resend puts the recipient(s) in data.to (str or list)."""
    data = payload.get("data") or {}
    to = data.get("to") or payload.get("email") or ""
    if isinstance(to, str):
        return [to] if to else []
    if isinstance(to, list):
        return [t for t in to if isinstance(t, str) and t]
    return []


def handle_event(payload: dict) -> dict:
    """Map one verified Resend payload to a suppression write."""
    etype = payload.get("type") or ""
    reason = SUPPRESS_EVENTS.get(etype)
    if not reason:
        return {"status": "ignored", "type": etype}

    if not cloud_store.configured():
        return {"status": "store_unconfigured", "type": etype, "reason": reason}

    written = []
    for email in _recipients(payload):
        entry = cloud_store.add_suppression(
            email, reason,
            note=f"resend {etype} id={payload.get('id', '')}")
        if entry:
            written.append(email)
    return {"status": "suppressed", "type": etype, "reason": reason,
            "emails": written}


def handle_raw(body: bytes, headers: dict, secret: str,
               now: float = None) -> dict:
    """Verify + parse + process. Raises ValueError on bad signature/payload."""
    if not secret:
        raise ValueError("RESEND_WEBHOOK_SECRET not configured")
    if not verify_signature(body, headers, secret, now=now):
        raise ValueError("invalid Resend signature")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise ValueError("payload is not valid JSON")
    return handle_event(payload)


if __name__ == "__main__":
    # Self-test: signature round-trip + event mapping
    secret = "whsec_test_secret"
    payload = json.dumps({
        "type": "email.clicked",
        "id": "evt_test_1",
        "data": {"to": "lead@example.com", "subject": "baseline"},
    }).encode()
    now = time.time()
    ts = str(int(now))
    signed = f"msg_test.{ts}.{payload.decode()}"
    mac = hmac.new(secret.encode(), signed.encode(), hashlib.sha256)
    headers = {
        "svix-id": "msg_test",
        "svix-timestamp": ts,
        "svix-signature": "v1," + base64.b64encode(mac.digest()).decode(),
    }
    assert verify_signature(payload, headers, secret, now=now), "sig round-trip"
    assert not verify_signature(payload, headers, "wrong", now=now), "bad secret"
    assert not verify_signature(payload, {**headers, "svix-timestamp": str(int(now) - 4000)},
                                secret, now=now), "stale timestamp"
    result = handle_event(json.loads(payload))
    print("self-test OK:", result["status"])
