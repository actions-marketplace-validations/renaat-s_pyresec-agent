"""Lightweight notification helpers for Cloud Run (Resend + Telegram).

Used by stripe_webhook.py to send intake emails + internal alerts.
Avoids importing heavy scripts like git_scraper or telegram_app.
"""

import os
import httpx

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
PYRESEC_SENDER = os.getenv("PYRESEC_SENDER", "onboarding@resend.dev")
PYRESEC_FROM_NAME = os.getenv("PYRESEC_FROM_NAME", "PYRESEC Agent")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
BASE_URL = os.getenv("PYRESEC_URL",
                     "https://pyresec-agent-519576377065.us-central1.run.app")


def _branded_html(title: str, paragraphs: list[str]) -> str:
    """PYRESEC-branded HTML email (dark glass card style)."""
    body = "".join(
        f'<p style="color:#ccc;font-size:15px;margin:0 0 16px;text-align:center;line-height:1.6;">{p}</p>'
        for p in paragraphs
    )
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#050505;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#050505;padding:40px 20px;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="background:rgba(15,15,15,0.9);border-radius:16px;border:2px solid rgba(255,255,255,0.25);overflow:hidden;">
  <tr><td style="padding:48px 40px 40px;border-bottom:2px solid rgba(255,255,255,0.25);" align="center">
    <div style="color:#fff;font-size:42px;font-weight:800;letter-spacing:6px;margin:0 0 8px 0;">PYRESEC</div>
    <div style="color:#999;font-size:17px;letter-spacing:3px;text-transform:uppercase;">AI Code Security Engine</div>
  </td></tr>
  <tr><td style="padding:36px 40px;" align="center">
    <h2 style="color:#fff;font-size:24px;margin:0 0 24px;text-align:center;">{title}</h2>
    {body}
  </td></tr>
  <tr><td style="padding:40px 40px;border-top:2px solid rgba(255,255,255,0.25);" align="center">
    <div style="color:#888;font-size:13px;text-align:center;line-height:1.6;">
      NanoClone Systems Ltd.<br>
      A NanoClone Life Sciences company<br>
      <a href="{BASE_URL}/services" style="color:#dc2626;text-decoration:none;">Engagement details</a> |
      <a href="{BASE_URL}/docs" style="color:#dc2626;text-decoration:none;">Methodology</a>
    </div>
  </td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""


def send_email(to: str, subject: str, text_body: str, html_body: str = "") -> bool:
    """Send via Resend. Returns True on 200/201."""
    if not RESEND_API_KEY:
        return False
    payload = {
        "from": f"{PYRESEC_FROM_NAME} <{PYRESEC_SENDER}>",
        "to": [to],
        "subject": subject,
        "text": text_body,
    }
    if html_body:
        payload["html"] = html_body
    try:
        r = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}",
                     "Content-Type": "application/json"},
            json=payload,
            timeout=30.0,
        )
        return r.status_code in (200, 201)
    except Exception:
        return False


def send_telegram_alert(text: str) -> bool:
    """Send an HTML alert to the configured Telegram chat."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        r = httpx.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text,
                  "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=30.0,
        )
        return r.status_code == 200
    except Exception:
        return False


def send_remediation_intake_email(to: str) -> bool:
    """Post-purchase intake for the $750 one-time remediation engagement."""
    subject = "Your PYRESEC Proof-Led Remediation is active — 48h delivery"
    text = """Thank you for choosing PYRESEC.

Your Proof-Led Remediation engagement is now active.

Delivery SLA: 48 hours from the moment we receive your repository details.

To get started, simply reply to this email with:
  1. The GitHub repository URL (e.g. https://github.com/your-org/your-protocol)
  2. The branch you want us to focus on (e.g. main or master)

We will run a full automated audit + LLM remediation pass, manually review the generated patch and signed PDF, and deliver both back to you within 48 hours.

Questions? Just reply to this email.

— PYRESEC Agent
NanoClone Systems Ltd.
"""
    html = _branded_html("Proof-Led Remediation Active", [
        "Thank you for choosing PYRESEC.",
        "Your <strong style=\"color:#fff;\">Proof-Led Remediation</strong> engagement is now active.",
        "<strong style=\"color:#22c55e;\">Delivery SLA:</strong> 48 hours from the moment we receive your repository details.",
        "To get started, simply reply to this email with:<br><br>"
        "1. The GitHub repository URL<br>"
        "(e.g. https://github.com/your-org/your-protocol)<br><br>"
        "2. The branch you want us to focus on<br>"
        "(e.g. main or master)",
        "We will run a full automated audit + LLM remediation pass, manually review the generated patch and signed PDF, and deliver both back to you within 48 hours.",
    ])
    return send_email(to, subject, text, html)


def send_monitoring_intake_email(to: str) -> bool:
    """Post-purchase welcome for the $495/mo continuous monitoring retainer."""
    subject = "Welcome to PYRESEC Continuous Monitoring"
    text = """Welcome to PYRESEC Continuous Monitoring.

Your retainer is active and your weekly cadence begins as soon as we receive your repository details.

To onboard, reply to this email with:
  1. The GitHub repository URL (e.g. https://github.com/your-org/your-protocol)
  2. The branch you want monitored (we currently support public main/master branches only)

What happens each week:
  • We re-scan your public default branch for new vulnerabilities
  • We diff the results against the previous baseline
  • You receive a clean markdown delta report by email
  • Critical or High findings are flagged immediately

Scope note: This tier currently supports public main/master branches only. Private repository access is planned for a future release.

— PYRESEC Agent
NanoClone Systems Ltd.
"""
    html = _branded_html("Continuous Monitoring Active", [
        "Welcome to <strong style=\"color:#fff;\">PYRESEC Continuous Monitoring</strong>.",
        "Your retainer is active and your weekly cadence begins as soon as we receive your repository details.",
        "To onboard, reply to this email with:<br><br>"
        "1. The GitHub repository URL<br>"
        "(e.g. https://github.com/your-org/your-protocol)<br><br>"
        "2. The branch you want monitored<br>"
        "<span style=\"color:#dc2626;\">We currently support public main/master branches only.</span>",
        "<strong style=\"color:#fff;\">What happens each week:</strong><br>"
        "• Re-scan of your public default branch<br>"
        "• Diff against the previous baseline<br>"
        "• Clean markdown delta report by email<br>"
        "• Critical/High findings flagged immediately",
    ])
    return send_email(to, subject, text, html)
