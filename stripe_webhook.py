"""PYRESEC Stripe webhook → revenue ledger sync.

Receives checkout.session.completed / invoice.paid deliveries, verifies the
Stripe-Signature header (manual HMAC-SHA256, stdlib only), and moves the
payment into the ledger as closed_won — exactly once per payment ref.

Route wiring lives in main.py:  POST /v1/webhooks/stripe
"""

import os
import hmac
import hashlib
import json
import time

from scripts import revenue_ledger
import notify

TOLERANCE_SECONDS = 300

# Event types that represent money received
WON_EVENTS = ("checkout.session.completed", "invoice.paid")


def verify_signature(body: bytes, sig_header: str, secret: str,
                     now: float = None) -> bool:
    """Verify Stripe's Stripe-Signature header.

    Format: t=<unix_ts>,v1=<hexdigest>[,v1=...]
    Signed payload: f"{t}.{raw_body}" hashed with HMAC-SHA256(secret).
    """
    if not body or not sig_header or not secret:
        return False
    parts = {}
    for kv in sig_header.split(","):
        if "=" in kv:
            k, v = kv.split("=", 1)
            parts.setdefault(k.strip(), []).append(v.strip())
    ts_values = parts.get("t", [])
    sig_values = parts.get("v1", [])
    if not ts_values or not sig_values:
        return False
    try:
        ts = int(ts_values[0])
    except ValueError:
        return False
    current = now if now is not None else time.time()
    if abs(current - ts) > TOLERANCE_SECONDS:
        return False
    expected = hmac.new(
        secret.encode("utf-8"),
        f"{ts}.".encode("utf-8") + body,
        hashlib.sha256,
    ).hexdigest()
    return any(hmac.compare_digest(expected, v) for v in sig_values)


def _infer_model(amount_usd: float, metadata: dict) -> str:
    """metadata.model wins; else exact known price; else nearest tier."""
    model = (metadata.get("model") or "").strip().lower()
    if model in revenue_ledger.MODELS:
        return model
    cents = round(amount_usd * 100)
    if cents == 75000:
        return "remediation"
    if cents == 49500:
        return "monitoring"
    return "remediation" if amount_usd >= 600 else "monitoring"


def process_event(event: dict, now: float = None) -> dict:
    """Translate one verified Stripe event into a ledger entry.

    Returns {"status": "recorded"|"duplicate"|"ignored", ...}.
    Idempotent: replays of the same payment ref are duplicates.
    """
    etype = event.get("type") or ""
    obj = ((event.get("data") or {}).get("object")) or {}

    if etype not in WON_EVENTS:
        return {"status": "ignored", "type": etype}

    if etype == "invoice.paid":
        # subscription_create invoices mirror the first checkout.session —
        # counting them too would double-charge the ledger for one payment.
        reason = obj.get("billing_reason")
        if reason not in ("subscription_cycle", "subscription_update"):
            return {"status": "ignored", "type": f"invoice.paid/{reason}"}
        ref = obj.get("id") or ""
        amount = (obj.get("amount_paid") or obj.get("amount_due") or 0) / 100.0
        metadata = obj.get("metadata") or {}
        currency = obj.get("currency") or ""
        lead = metadata.get("lead") or metadata.get("repo") or ""
    else:
        metadata = obj.get("metadata") or {}
        ref = (metadata.get("scan_id")
               or obj.get("client_reference_id")
               or obj.get("id") or "")
        amount = (obj.get("amount_total") or 0) / 100.0
        currency = obj.get("currency") or ""
        lead = metadata.get("lead") or metadata.get("repo") or ""

    if amount <= 0:
        return {"status": "ignored", "type": etype, "reason": "zero amount"}

    model = _infer_model(amount, metadata)
    note = f"stripe {etype} {obj.get('id', '')}".strip()
    if currency:
        note += f" ({currency})"

    entry = revenue_ledger.mark_won(
        model, amount, ref=ref, lead=lead, channel="stripe", note=note)

    if entry is None:
        return {"status": "duplicate", "ref": ref}

    result = {"status": "recorded", "model": model, "amount": amount, "ref": ref}

    # --- concierge notifications (only on first recorded payment, not retries) ---
    customer_email = ""
    if etype == "checkout.session.completed":
        details = obj.get("customer_details") or {}
        customer_email = details.get("email") or obj.get("customer_email") or ""
        if customer_email:
            if model == "remediation":
                notify.send_remediation_intake_email(customer_email)
            elif model == "monitoring":
                notify.send_monitoring_intake_email(customer_email)

    emoji = "💰" if etype == "checkout.session.completed" else "🔄"
    notify.send_telegram_alert(
        f"{emoji} <b>STRIPE {model.upper()}</b>\n"
        f"Amount: ${amount:.2f}\n"
        f"Ref: <code>{ref}</code>\n"
        f"Email: {customer_email or 'n/a'}\n"
        f"Event: {etype}"
    )

    return result


def handle_raw(body: bytes, sig_header: str, secret: str,
               now: float = None) -> dict:
    """Verify + parse + process. Raises ValueError on bad signature/payload."""
    if not secret:
        raise ValueError("STRIPE_WEBHOOK_SECRET not configured")
    if not verify_signature(body, sig_header, secret, now=now):
        raise ValueError("invalid Stripe signature")
    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        raise ValueError("payload is not valid JSON")
    return process_event(event, now=now)


if __name__ == "__main__":
    import tempfile
    # Self-test: signature round-trip + idempotent ledger sync
    secret = "whsec_test_secret"
    payload = json.dumps({
        "type": "checkout.session.completed",
        "data": {"object": {
            "id": "cs_test_123", "amount_total": 75000, "currency": "usd",
            "client_reference_id": "scan-abc", "metadata": {},
            "customer_details": {"email": "buyer@example.com", "name": "Test Buyer"},
        }},
    }).encode()
    ts = int(time.time())

    def _sign(body: bytes) -> str:
        sig = hmac.new(secret.encode(), f"{ts}.".encode() + body,
                       hashlib.sha256).hexdigest()
        return f"t={ts},v1={sig}"

    header = _sign(payload)

    assert verify_signature(payload, header, secret)
    assert not verify_signature(payload, header, "whsec_wrong")
    assert not verify_signature(payload, f"t={ts},v1={'0' * 64}", secret)
    assert not verify_signature(
        payload, f"t={ts - 9999},v1={header.split('v1=')[1]}", secret)

    os.environ["REVENUE_LEDGER_FILE"] = os.path.join(
        tempfile.gettempdir(), "pyresec_webhook_selftest.json")
    if os.path.exists(os.environ["REVENUE_LEDGER_FILE"]):
        os.remove(os.environ["REVENUE_LEDGER_FILE"])

    # Prevent the self-test from sending real emails/Telegrams
    sent_emails, sent_alerts = [], []
    notify.send_remediation_intake_email = lambda x: sent_emails.append(("remediation", x)) or True
    notify.send_monitoring_intake_email = lambda x: sent_emails.append(("monitoring", x)) or True
    notify.send_telegram_alert = lambda x: sent_alerts.append(x) or True

    r1 = handle_raw(payload, header, secret)
    r2 = handle_raw(payload, header, secret)  # Stripe retry

    # subscription_create invoice should be ignored (avoids double count)
    inv_create = json.dumps({"type": "invoice.paid", "data": {"object": {
        "id": "in_1", "billing_reason": "subscription_create",
        "amount_paid": 49500, "currency": "usd"}}}).encode()
    r3 = handle_raw(inv_create, _sign(inv_create), secret)

    # subscription_cycle invoice is a real renewal
    inv_cycle = json.dumps({"type": "invoice.paid", "data": {"object": {
        "id": "in_2", "billing_reason": "subscription_cycle",
        "amount_paid": 49500, "currency": "usd", "metadata": {}}}}).encode()
    r4 = handle_raw(inv_cycle, _sign(inv_cycle), secret)

    summary = revenue_ledger.summary()
    os.remove(os.environ["REVENUE_LEDGER_FILE"])

    assert r1["status"] == "recorded" and r1["model"] == "remediation"
    assert r2["status"] == "duplicate"
    assert r3["status"] == "ignored"
    assert r4["status"] == "recorded" and r4["model"] == "monitoring"
    assert summary["counts_by_stage"].get("closed_won") == 2
    assert summary["total_revenue"] == 1245.0
    assert any(t == "remediation" for t, _ in sent_emails)
    assert len(sent_alerts) == 2  # checkout + renewal, not the duplicate or create invoice
    print("SELF-TEST PASS:", r1, "| retry:", r2["status"],
          "| create-invoice:", r3["status"], "| renewal:", r4["status"],
          "| revenue:", summary["total_revenue"],
          "| alerts:", len(sent_alerts))
