"""PYRESEC Follow-Up Engine — 3-touch outbound sequence.

B2B outbound needs 3-5 touches; we currently send exactly one. This closes
the gap:

  Touch 0 (Day 0): proof email        — git_scraper via Telegram approval
  Touch 1 (Day 3): "did you see the line-level references?" nudge
  Touch 2 (Day 7): value giveaway (endpoint hardening checklist) + retainer

A lead stops receiving follow-ups when the revenue ledger records closed_won
for that repo (they paid) or when both touches have been sent.

State file : scripts/.followup_state.json   {repo: {"fu1": iso, "fu2": iso}}
Run log    : scripts/.followup_runs.json    (last 100 runs)

CLI:
  python scripts/followup_engine.py --dry-run
  python scripts/followup_engine.py
"""

import os
import sys
import json
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
except Exception:
    pass

import httpx
from scripts import email_audit, revenue_ledger

QUEUE_FILE = Path("scripts/.reply_queue.json")
STATE_FILE = Path("scripts/.followup_state.json")
RUNS_FILE = Path("scripts/.followup_runs.json")

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
PYRESEC_SENDER = os.getenv("PYRESEC_SENDER", "onboarding@resend.dev")
PYRESEC_FROM_NAME = os.getenv("PYRESEC_FROM_NAME", "PYRESEC Agent")
CALENDLY = os.getenv("CALENDLY_URL", "").strip()
SERVICES_URL = os.getenv("PYRESEC_URL",
                         "https://pyresec-agent-519576377065.us-central1.run.app") + "/services"
DOCS_URL = os.getenv("PYRESEC_DOCS_URL",
                     "https://pyresec-agent-519576377065.us-central1.run.app/docs")

DAY1_THRESHOLD = 3   # follow-up 1 sends at 3+ days
DAY2_THRESHOLD = 7   # follow-up 2 sends at 7+ days


# ==================== STATE ====================

def _load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default
    return default


def load_state() -> dict:
    return _load_json(STATE_FILE, {})


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def log_run(summary: dict):
    runs = _load_json(RUNS_FILE, [])
    runs.append(summary)
    RUNS_FILE.write_text(json.dumps(runs[-100:], indent=2, ensure_ascii=False), encoding="utf-8")


# ==================== LEAD EXTRACTION ====================

def collect_sent_leads() -> list[dict]:
    """Flatten sent email_batch queue entries into per-lead dicts."""
    queue = _load_json(QUEUE_FILE, [])
    leads = []
    for entry in queue:
        if entry.get("kind") != "email_batch" or entry.get("status") != "sent":
            continue
        created = entry.get("created_at") or ""
        try:
            sent_at = datetime.fromisoformat(created)
        except ValueError:
            continue
        for item in entry.get("emails", []):
            leads.append({
                "to": item.get("to", ""),
                "repo": item.get("repo", ""),
                "playbook": item.get("playbook", "monitoring"),
                "original_subject": item.get("subject", ""),
                "sent_at": sent_at,
            })
    return leads


def paid_repos() -> set[str]:
    """Repos the revenue ledger has recorded as closed_won."""
    data = _load_json(Path(revenue_ledger._ledger_path()), {"events": []})
    return {
        (ev.get("lead") or "").strip().lower()
        for ev in data.get("events", [])
        if ev.get("stage") == "closed_won"
    }


def fetch_pipeline_state() -> dict | None:
    """Pull shared state from production (cloud_store via /v1/pipeline/state).

    Returns {"suppressions": [...], "paid": [...]} or None when the endpoint
    is unreachable / unconfigured — callers fail open with a warning so a
    production blip never silently kills the whole sequence.
    """
    base = os.getenv("PRODUCTION_URL",
                     "https://pyresec-agent-519576377065.us-central1.run.app").rstrip("/")
    token = os.getenv("PIPELINE_TOKEN", "").strip()
    if not token:
        print("  [WARN] PIPELINE_TOKEN not set — running without suppression sync")
        return None
    try:
        r = httpx.get(f"{base}/v1/pipeline/state",
                      headers={"X-Pipeline-Token": token}, timeout=8.0)
        if r.status_code != 200:
            print(f"  [WARN] pipeline state HTTP {r.status_code} — failing open")
            return None
        return r.json()
    except Exception as exc:
        print(f"  [WARN] pipeline state unreachable ({exc}) — failing open")
        return None


def suppressed_emails(state: dict | None) -> set[str]:
    if not state:
        return set()
    return {
        (item.get("email") or "").strip().lower()
        for item in state.get("suppressions", [])
        if item.get("email")
    }


def cloud_paid_leads(state: dict | None) -> set[str]:
    """Repos/leads the production Stripe webhook has recorded as paid."""
    if not state:
        return set()
    return {
        (item.get("lead") or "").strip().lower()
        for item in state.get("paid", [])
        if item.get("lead")
    }


# ==================== EMAIL CONTENT ====================

def _branded_html(title: str, paragraphs: list[str]) -> str:
    base = os.getenv("PRODUCTION_URL",
                     "https://pyresec-agent-519576377065.us-central1.run.app")
    body = "".join(
        f'<p style="color:#ccc;font-size:15px;margin:0 0 16px;text-align:left;'
        f'line-height:1.6;">{p}</p>'
        for p in paragraphs
    )
    cal = (f'<p style="margin:24px 0;text-align:center;">'
           f'<a href="{CALENDLY}" target="_blank" rel="noopener" '
           f'style="background:#dc2626;color:#000;font-weight:700;padding:12px 28px;'
           f'border-radius:100px;text-decoration:none;">Book a Call — 30 min</a></p>'
           if CALENDLY else "")
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#050505;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#050505;padding:40px 20px;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="background:rgba(15,15,15,0.9);border-radius:16px;border:2px solid rgba(255,255,255,0.25);overflow:hidden;">
  <tr><td style="padding:48px 40px 40px;border-bottom:2px solid rgba(255,255,255,0.25);" align="center">
    <img src="{base}/static/pyresec.png" width="100" height="100" alt="PYRESEC" style="display:block;margin:0 auto 20px auto;border-radius:20px;">
    <div style="color:#fff;font-size:42px;font-weight:800;letter-spacing:6px;margin:0 0 8px 0;">PYRESEC</div>
    <div style="color:#999;font-size:17px;letter-spacing:3px;text-transform:uppercase;">AI Code Security Engine</div>
  </td></tr>
  <tr><td style="padding:36px 40px;" align="left">
    <h2 style="color:#fff;font-size:22px;margin:0 0 20px;text-align:left;">{title}</h2>
    {body}
    {cal}
  </td></tr>
  <tr><td style="padding:40px 40px;border-top:2px solid rgba(255,255,255,0.25);" align="center">
    <img src="{base}/static/nanoclone.png" height="64" alt="NanoClone Systems" style="display:block;margin:0 auto;">
    <div style="color:#888;font-size:13px;text-align:center;line-height:1.6;">
      NanoClone Systems Ltd.<br>
      <a href="{SERVICES_URL}" style="color:#dc2626;text-decoration:none;">Engagement details</a> |
      <a href="{DOCS_URL}" style="color:#dc2626;text-decoration:none;">Methodology</a>
    </div>
  </td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""


def followup1(lead: dict) -> tuple[str, str, str]:
    """Day 3 nudge — assume it was read on a phone and forgotten."""
    repo = lead["repo"]
    original = lead["original_subject"]
    text = f"""Hi there,

Just wanted to ensure you saw the line-level references I sent over regarding
{repo}. Did your team have a chance to review them?

Re: {original}

If the findings are clearer when someone walks you through them, I'm happy to
do that directly:
{CALENDLY}

Or simply reply to this email with any question — a repo URL works too.

- PYRESEC, NanoClone Systems Ltd.
  You receive this because we sent a security baseline for {repo}.
"""
    html = _branded_html("Did you see the baseline for your repo?", [
        f"Just wanted to ensure you saw the <strong style=\"color:#fff;\">line-level "
        f"references</strong> I sent over regarding <strong style=\"color:#fff;\">{repo}</strong>. "
        f"Did your team have a chance to review them?",
        f"Reference: <em style=\"color:#999;\">{original}</em>",
        "If the findings are clearer when someone walks you through them, use the "
        "button below or simply reply to this email — a repo URL works too.",
    ])
    return (f"Re: {original}", text, html)


HARDENING_CHECKLIST = """FREE — Endpoint Hardening Checklist (FastAPI + Web3 teams)

1. Validation     — Pydantic models on every request body; reject extra fields.
2. AuthN/AuthZ    — verify JWT signature + issuer + expiry on every protected route.
3. CORS           — explicit origin allowlist; never "*" in production.
4. Secrets        — env/secret manager only; scan history for leaked keys.
5. RPC hygiene    — pin chain IDs and RPC endpoints; validate calldata before signing.
6. Rate limiting  — per-IP and per-key limits on every paid endpoint.
7. Dependency drift — lockfiles committed; automated update PRs + CVE watch.
8. Error leakage — generic 500s; never ship stack traces or SQL in responses.
9. Webhooks       — constant-time signature comparison on every callback.
10. Logging       — structured logs, no PII, no private keys.

Run this list before every mainnet deploy — or we watch it weekly for you."""


def followup2(lead: dict) -> tuple[str, str, str]:
    """Day 7 — give away real value, then restate the retainer."""
    repo = lead["repo"]
    original = lead["original_subject"]
    price = os.getenv("PRICE_RETAINER", "$495/mo")
    stripe = os.getenv("STRIPE_LINK_RETAINER", "")
    payment_line = (f"Activate: {stripe}" if stripe
                    else "Reply MONITOR and we'll send a payment link.")
    text = f"""Hi there,

One more thing on {repo} — a free checklist our engine runs against every
baseline. Steal it:

{HARDENING_CHECKLIST}

Most teams we scan tick 7 of 10 on the first pass. The ones that worry us are
dependency drift and webhook signature checks — both are exactly what the
{price} monitoring retainer watches continuously:

  * Weekly re-scan of your default branch (diff-aware)
  * Dependency CVE watch across your lockfiles
  * Monthly signed PDF baseline — SHA-verifiable for auditors and investors

{payment_line}

{CALENDLY}

- PYRESEC, NanoClone Systems Ltd.
  You receive this because we sent a security baseline for {repo}.
"""
    checklist_html = "".join(
        f'<div style="color:#ccc;font-size:14px;margin:0 0 10px;line-height:1.5;">'
        f'<span style="color:#22c55e;font-family:monospace;">{line[:line.index("—") if "—" in line else 12].strip()}</span>'
        f'{line[line.index("—") if "—" in line else 12:]}</div>'
        for line in HARDENING_CHECKLIST.splitlines()[2:] if line.strip()
    )
    html = _branded_html("Free: Endpoint Hardening Checklist", [
        f"One more thing on <strong style=\"color:#fff;\">{repo}</strong> — a free "
        "checklist our engine runs against every baseline. Steal it:",
        checklist_html + '<div style="height:8px;"></div>',
        "Most teams tick 7 of 10 on the first pass. The ones that worry us are "
        "<strong style=\"color:#fff;\">dependency drift</strong> and "
        "<strong style=\"color:#fff;\">webhook signature checks</strong> — both are "
        "exactly what the monitoring retainer watches continuously.",
        "Weekly re-scan · CVE watch across lockfiles · Monthly signed PDF baseline "
        "(SHA-verifiable for auditors and investors).",
    ])
    return (f"Re: {original} — endpoint hardening checklist", text, html)


# ==================== SEND ====================

def send_followup(to: str, subject: str, text: str, html: str, stage: int) -> bool:
    if not RESEND_API_KEY:
        print(f"  [SKIP] RESEND_API_KEY not set")
        return False
    payload = {
        "from": f"{PYRESEC_FROM_NAME} <{PYRESEC_SENDER}>",
        "to": [to],
        "subject": subject,
        "text": text,
        "html": html,
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post("https://api.resend.com/emails",
                               headers={"Authorization": f"Bearer {RESEND_API_KEY}",
                                        "Content-Type": "application/json"},
                               json=payload)
        ok = resp.status_code in (200, 201)
        email_audit.log_email(
            to, subject, source=f"followup_engine.stage{stage}",
            status="success" if ok else "failed",
            error="" if ok else f"{resp.status_code}: {resp.text[:200]}",
        )
        if not ok:
            print(f"  [ERROR] {resp.status_code}: {resp.text[:200]}")
        return ok
    except Exception as e:
        email_audit.log_email(to, subject, f"followup_engine.stage{stage}", "failed", str(e))
        print(f"  [ERROR] {e}")
        return False


# ==================== MAIN ====================

def run(dry_run: bool = False) -> dict:
    now = datetime.now(timezone.utc)
    state = load_state()
    leads = collect_sent_leads()
    paid = paid_repos()
    pipeline = fetch_pipeline_state()
    paid |= cloud_paid_leads(pipeline)
    suppressed = suppressed_emails(pipeline)

    summary = {"timestamp": now.isoformat(), "dry_run": dry_run,
               "leads_considered": len(leads),
               "suppression_sync": pipeline is not None,
               "sent": [], "skipped": {"paid": 0, "not_due": 0, "done": 0,
                                       "suppressed": 0}}

    for lead in leads:
        repo = (lead["repo"] or "").strip()
        key = repo.lower()
        if not key:
            continue
        if key in paid:
            summary["skipped"]["paid"] += 1
            continue
        if (lead["to"] or "").strip().lower() in suppressed:
            summary["skipped"]["suppressed"] += 1
            continue

        age = now - lead["sent_at"]
        age_days = age.total_seconds() / 86400
        st = state.setdefault(key, {})

        for stage, threshold, builder in (
            (1, DAY1_THRESHOLD, followup1),
            (2, DAY2_THRESHOLD, followup2),
        ):
            flag = f"fu{stage}"
            if st.get(flag):
                continue
            if age_days < threshold:
                summary["skipped"]["not_due"] += 1
                continue
            if stage == 2 and not st.get("fu1"):
                summary["skipped"]["not_due"] += 1  # keep sequence order
                continue

            subject, text, html = builder(lead)
            if dry_run:
                print(f"  [DRY RUN] stage {stage} -> {lead['to']} ({repo}, {int(age_days)}d)")
                print(f"      subject: {subject}")
                summary["sent"].append({"stage": stage, "to": lead["to"], "repo": repo, "dry": True})
                break

            print(f"  [SEND] stage {stage} -> {lead['to']} ({repo}, {int(age_days)}d old)")
            if send_followup(lead["to"], subject, text, html, stage):
                st[flag] = now.isoformat()
                summary["sent"].append({"stage": stage, "to": lead["to"], "repo": repo})
            break  # one touch per run per lead

        if st.get("fu1") and st.get("fu2"):
            summary["skipped"]["done"] += 1

    if not dry_run:
        save_state(state)
    log_run(summary)
    return summary


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="PYRESEC Follow-Up Engine")
    p.add_argument("--dry-run", action="store_true", help="Preview only")
    args = p.parse_args()

    print("=" * 60)
    print("  PYRESEC FOLLOW-UP ENGINE" + ("  (DRY RUN)" if args.dry_run else ""))
    print("=" * 60)
    s = run(dry_run=args.dry_run)
    print(f"  Leads considered: {s['leads_considered']}")
    print(f"  Sent: {len(s['sent'])}")
    print(f"  Skipped: {s['skipped']}")
    print("=" * 60)
