"""PYRESEC Playbooks — high-ticket business models running on one engine.

Two models, proven demand:

  remediation : proof-led one-time engagement ($750). We disclose the real
                finding for free (proof), charge for the verified fix +
                signed assessment PDF.
  monitoring  : recurring retainer ($495/mo). Weekly re-scan, diff report,
                dependency CVE watch.

Every playbook = ICP scoring + proof formatting + outreach copy + payment
links. The engines (git_scraper, social_scanner) stay generic; copy and
qualification live here.
"""

import os
from html import escape
from typing import Optional

try:  # explicit .env path — order/cwd independent (constants read below)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))
except Exception:
    pass

# ==================== PRICING & RAILS ====================

PRICE_REMEDIATION = os.getenv("PRICE_REMEDIATION", "$750")
PRICE_RETAINER = os.getenv("PRICE_RETAINER", "$495/mo")
STRIPE_REMEDIATION = os.getenv("STRIPE_LINK_REMEDIATION", "")
STRIPE_RETAINER = os.getenv("STRIPE_LINK_RETAINER", "")
DOCS_URL = os.getenv("PYRESEC_DOCS_URL",
                     "https://pyresec-agent-519576377065.us-central1.run.app/docs")
BASE_URL = os.getenv("PYRESEC_URL",
                     "https://pyresec-agent-519576377065.us-central1.run.app")
SERVICES_URL = f"{BASE_URL}/services"

ICP_MIN_SCORE = int(os.getenv("ICP_MIN_SCORE", "45"))

# ==================== ICP SCORING ====================

ICP_TOPICS = {
    "defi", "web3", "blockchain", "solidity", "smart-contracts",
    "ethereum", "protocol", "fintech", "security", "cryptocurrency",
    "layer-2", "cross-chain", "wallet", "payments",
}
ICP_DESC_WORDS = (
    "protocol", "production", "mainnet", "testnet", "api", "platform",
    "infrastructure", "settlement", "custody", "exchange",
)


def score_repo(repo: dict) -> int:
    """Score a GitHub repo dict against the funded-team ICP. 0-100+."""
    score = 0

    stars = repo.get("stargazers_count") or 0
    if stars >= 1000:
        score += 40
    elif stars >= 200:
        score += 32
    elif stars >= 50:
        score += 24
    elif stars >= 10:
        score += 12

    if repo.get("homepage"):
        score += 15  # has a website = likely a company/protocol

    topics = set(repo.get("topics") or [])
    if topics & ICP_TOPICS:
        score += 15

    desc = (repo.get("description") or "").lower()
    if any(w in desc for w in ICP_DESC_WORDS):
        score += 10

    pushed = repo.get("pushed_at") or ""
    if pushed >= "2026-09":  # active within ~2 weeks of 2026-09-28
        score += 10

    if repo.get("license"):
        score += 5
    if desc:
        score += 5

    return score


def qualifies(repo: dict) -> bool:
    return score_repo(repo) >= ICP_MIN_SCORE


# ==================== PROOF FORMATTING ====================

SEV_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


def top_findings(scan: dict, n: int = 3) -> list[dict]:
    findings = list(scan.get("sast_findings") or [])
    findings += list(scan.get("sca_findings") or [])
    findings.sort(key=lambda f: SEV_ORDER.get((f.get("severity") or "LOW").upper(), 4))
    return findings[:n]


def proof_summary(scan: dict, n: int = 3) -> str:
    """Plain-text proof block — the free disclosure that opens the deal."""
    findings = top_findings(scan, n)
    if not findings:
        return ("Automated analysis of the current code returned no actionable "
                "findings — a monitoring baseline is still worth locking in.")
    lines = []
    for f in findings:
        sev = (f.get("severity") or "?").upper()
        cwe = f.get("cwe") or f.get("cve") or ""
        loc = f"line {f['line_number']}" if f.get("line_number") else (f.get("package") or "")
        lines.append(f"[{sev}] {f.get('type', 'finding')} {cwe}"
                     + (f" ({loc})" if loc else ""))
        if f.get("description"):
            lines.append(f"    {str(f['description'])[:160]}")
        if f.get("line_content"):
            lines.append(f"    > {str(f['line_content'])[:120]}")
    return "\n".join(lines)


def risk_rating(scan: dict) -> str:
    for f in (scan.get("sast_findings") or []) + (scan.get("sca_findings") or []):
        if (f.get("severity") or "").upper() in ("CRITICAL", "HIGH"):
            return (f.get("severity") or "").upper()
    if (scan.get("sast_findings") or scan.get("sca_findings") or scan.get("gas_findings")):
        return "MEDIUM"
    return "CLEAN"


# ==================== PLAYBOOK SELECTION ====================

def pick_playbook(scan: dict) -> str:
    """Serious findings sell the fix; clean code sells the watch."""
    return "remediation" if risk_rating(scan) in ("CRITICAL", "HIGH") else "monitoring"


def payment_lines(playbook: str) -> str:
    lines = []
    if playbook == "remediation":
        if STRIPE_REMEDIATION:
            lines.append(f"Card payment: {STRIPE_REMEDIATION}")
        lines.append(f"USDC on Base via x402: $500 flat - call "
                     f"{DOCS_URL} (remediate endpoint)")
    else:
        if STRIPE_RETAINER:
            lines.append(f"Activate monitoring: {STRIPE_RETAINER}")
        lines.append(f"Or reply 'MONITOR' and we'll send a USDC (x402) subscription link.")
    return "\n".join(lines)


# ==================== HTML EMAIL (original design, HT content) ====================

def _risk_counts(scan: dict) -> str:
    counts = {}
    for f in (scan.get("sast_findings") or []) + (scan.get("sca_findings") or []):
        sev = (f.get("severity") or "?").upper()
        counts[sev] = counts.get(sev, 0) + 1
    return ", ".join(f"{v} {k.lower()}" for k, v in counts.items()) or "clean"


def _email_html(kind: str, lead: dict, scan: dict) -> str:
    """HTML email — the original PYRESEC design (logo header, glass card,
    proof block, feature row, chips strip, NanoClone footer). Only the
    content markets the two high-ticket products."""
    logo_base = f"{BASE_URL}/static"
    repo = lead.get("repo") or lead.get("full_name") or "your repository"
    name = (lead.get("name") or "").split()[0:1]
    hi = f"Hi {escape(name[0])}," if name else "Hi,"
    rating = escape(risk_rating(scan))
    proof = escape(proof_summary(scan, 3))
    repo_e = escape(repo)

    if kind == "remediation":
        pitch = (f"Our security engine analyzed {repo_e} (public code) and confirmed "
                 f"<strong style=\"color:#fff;\">{rating}-rated exposure</strong>. "
                 f"The disclosure below is free - fork the fix yourself if you prefer. "
                 f"If you'd rather have it handled, we deliver a verified patch and a "
                 f"signed assessment PDF:")
        block_label = "FREE DISCLOSURE - PROOF ATTACHED"
        price_main = escape(PRICE_REMEDIATION)
        price_sub = "one-time"
        row_desc = ("Proof-Led Remediation<br>"
                    "Verified patch + signed assessment PDF<br>"
                    "Every finding with evidence + remediation notes")
        chips = [("Complete patch", "every flagged finding fixed"),
                 ("Signed PDF", "assessment report for your team"),
                 ("Evidence + CWE", "line refs + remediation notes")]
        cross = (f"Also available: Continuous Monitoring - {escape(PRICE_RETAINER)} - "
                 f"weekly re-scans, dependency CVE watch, regression alerts.")
        pay_parts = []
        if STRIPE_REMEDIATION:
            pay_parts.append(
                f'<a href="{escape(STRIPE_REMEDIATION)}" style="color:#dc2626;">'
                f'Pay by card - {escape(PRICE_REMEDIATION)} one-time</a>')
        pay_parts.append(
            f'<a href="{escape(DOCS_URL)}" style="color:#dc2626;">'
            f'USDC on Base via x402 - $500 flat</a>')
        pay_line = " &nbsp;&nbsp;|&nbsp;&nbsp; ".join(pay_parts)
    else:
        counts = escape(_risk_counts(scan))
        pitch = (f"We ran a security baseline on {repo_e}: {counts} "
                 f"({rating} rating). Code changes daily - what's clean today can "
                 f"regress after the next merge. For {escape(PRICE_RETAINER)} we "
                 f"watch it for you:")
        block_label = f"BASELINE RESULT - {rating} RATED"
        if "/" in PRICE_RETAINER:
            price_main, price_sub = PRICE_RETAINER.split("/", 1)
            price_main, price_sub = escape(price_main), "/" + price_sub.strip()
        else:
            price_main, price_sub = escape(PRICE_RETAINER), "per month"
        row_desc = ("Continuous Monitoring<br>"
                    "Weekly re-scan + dependency CVE watch<br>"
                    "Regression alerts + monthly PDF report")
        chips = [("Weekly re-scan", "diff-aware, default branch"),
                 ("CVE watch", "lockfile dependency alerts"),
                 ("Monthly PDF", "baseline report for your team")]
        cross = (f"Already seeing issues? Proof-Led Remediation fixes them for "
                 f"{escape(PRICE_REMEDIATION)} one-time - verified patch + signed PDF.")
        pay_parts = []
        if STRIPE_RETAINER:
            pay_parts.append(
                f'<a href="{escape(STRIPE_RETAINER)}" style="color:#dc2626;">'
                f'Activate monitoring - {escape(PRICE_RETAINER)}</a>')
        pay_parts.append("Reply 'MONITOR' for a USDC (x402) subscription link")
        pay_line = " &nbsp;&nbsp;|&nbsp;&nbsp; ".join(pay_parts)

    chip_cells = []
    for i, (main, sub) in enumerate(chips):
        if i:
            chip_cells.append('<td style="width:10px;"></td>')
        chip_cells.append(
            '<td style="background:rgba(255,255,255,0.04);border-radius:12px;'
            'border:2px solid rgba(255,255,255,0.3);padding:24px;text-align:center;'
            f'width:33%;"><div style="color:#fff;font-size:16px;font-weight:800;">{escape(main)}</div>'
            f'<div style="color:#999;font-size:13px;margin-top:6px;letter-spacing:1px;">{escape(sub)}</div></td>')
    chips_row = "".join(chip_cells)

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#050505;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#050505;padding:40px 20px;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="background:rgba(15,15,15,0.9);border-radius:16px;border:2px solid rgba(255,255,255,0.25);overflow:hidden;">

  <!-- Header -->
  <tr><td style="padding:48px 40px 40px;border-bottom:2px solid rgba(255,255,255,0.25);" align="center">
    <img src="{logo_base}/pyresec.png" width="100" height="100" alt="PYRESEC" style="display:block;margin:0 auto 20px auto;border-radius:20px;">
    <div style="color:#fff;font-size:42px;font-weight:800;letter-spacing:6px;margin:0 0 8px 0;">PYRESEC</div>
    <div style="color:#999;font-size:17px;letter-spacing:3px;text-transform:uppercase;">AI Code Security Engine</div>
  </td></tr>

  <!-- Body -->
  <tr><td style="padding:36px 40px;" align="center">
    <p style="color:#ccc;font-size:15px;margin:0 0 16px;text-align:center;">{hi}</p>
    <p style="color:#ccc;font-size:15px;margin:0 0 20px;text-align:center;">Noticed you just pushed a new project to GitHub (<a href="https://github.com/{repo_e}" style="color:#dc2626;">{repo_e}</a>).</p>
    <p style="color:#ccc;font-size:15px;margin:0 0 24px;text-align:center;">{pitch}</p>

    <!-- Proof Block -->
    <table width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 28px;"><tr><td style="background:rgba(255,255,255,0.04);border-radius:12px;border:2px solid rgba(255,255,255,0.3);padding:24px 28px;">
      <div style="color:#999;font-size:12px;letter-spacing:2px;text-transform:uppercase;margin:0 0 14px;text-align:center;">{block_label}</div>
      <code style="color:#22c55e;font-family:'SF Mono',Consolas,monospace;font-size:14px;white-space:pre-wrap;display:block;text-align:left;">{proof}</code>
    </td></tr></table>

    <!-- Price Row -->
    <table width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 28px;">
      <tr>
        <td style="background:rgba(255,255,255,0.04);border-radius:12px;border:2px solid rgba(255,255,255,0.3);padding:24px 28px;">
          <table width="100%" cellpadding="0" cellspacing="0"><tr>
            <td style="padding-right:24px;vertical-align:middle;text-align:center;"><span style="color:#22c55e;font-size:32px;font-weight:800;">{price_main}</span><br><span style="color:#888;font-size:13px;">{price_sub}</span></td>
            <td style="border-left:2px solid rgba(255,255,255,0.3);padding-left:24px;vertical-align:middle;"><span style="color:#ccc;font-size:14px;text-align:center;">{row_desc}</span></td>
          </tr></table>
        </td>
      </tr>
    </table>

    <!-- What's Included -->
    <table width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 28px;">
      <tr>
        {chips_row}
      </tr>
    </table>

    <p style="color:#888;font-size:14px;margin:0 0 24px;text-align:center;">{cross}<br>{pay_line}</p>

    <!-- Links -->
    <p style="margin:0;text-align:center;"><a href="{SERVICES_URL}" style="color:#dc2626;font-size:14px;text-decoration:none;">Engagement details</a> <span style="color:#444;">&nbsp;&nbsp;|&nbsp;&nbsp;</span> <a href="{DOCS_URL}" style="color:#dc2626;font-size:14px;text-decoration:none;">Methodology &amp; documentation</a></p>
  </td></tr>

  <!-- Footer -->
  <tr><td style="padding:40px 40px;border-top:2px solid rgba(255,255,255,0.25);" align="center">
    <img src="{logo_base}/nanoclone.png" height="64" alt="NanoClone Systems" style="display:block;margin:0 auto;">
  </td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""


# ==================== COPY: REMEDIATION (proof-led, one-time) ====================

def remediation_subject(lead: dict) -> str:
    repo = lead.get("repo") or lead.get("full_name") or "your repo"
    return f"Security finding in {repo} - proof attached"


def remediation_email(lead: dict, scan: dict, sender_name: str = "PYRESEC") -> tuple[str, str, str]:
    """Returns (subject, text_body, html_body). Finding-first, free disclosure, paid fix."""
    repo = lead.get("repo") or lead.get("full_name") or "your repository"
    name = (lead.get("name") or "").split()[0:1]
    hi = f"Hi {name[0]}," if name else "Hi,"
    rating = risk_rating(scan)
    proof = proof_summary(scan, 3)

    subject = remediation_subject(lead)
    body = f"""{hi}

Our security engine analyzed {repo} (public code) and confirmed {rating}-rated exposure:

{proof}

This disclosure is free - fork the fix yourself if you prefer. If you'd rather have it
handled and documented, we deliver:

  * Verified patch + signed assessment PDF (every finding, evidence, remediation notes)
    -> {PRICE_REMEDIATION} one-time
  * Continuous monitoring: weekly re-scans, dependency CVE watch, regression alerts
    -> {PRICE_RETAINER}

{payment_lines('remediation')}

Details and methodology: {DOCS_URL}

- {sender_name}, NanoClone Systems Ltd.
  You receive this because you committed to {repo}. One email; no follow-ups unless you reply.
"""
    return subject, body, _email_html("remediation", lead, scan)


# ==================== COPY: MONITORING (recurring retainer) ====================

def monitoring_subject(lead: dict) -> str:
    repo = lead.get("repo") or lead.get("full_name") or "your repo"
    return f"{repo}: security baseline ready (weekly monitoring available)"


def monitoring_email(lead: dict, scan: dict, sender_name: str = "PYRESEC") -> tuple[str, str, str]:
    """Returns (subject, text_body, html_body). Baseline result + recurring watch offer."""
    repo = lead.get("repo") or lead.get("full_name") or "your repository"
    name = (lead.get("name") or "").split()[0:1]
    hi = f"Hi {name[0]}," if name else "Hi,"
    rating = risk_rating(scan)
    proof = proof_summary(scan, 3)
    count_str = _risk_counts(scan)

    subject = monitoring_subject(lead)
    body = f"""{hi}

We ran a security baseline on {repo}: {count_str} ({rating} rating).

{proof}

Code changes daily - what's clean today can regress after the next merge. For
{PRICE_RETAINER} we watch it for you:

  * Weekly re-scan of the default branch (diff-aware)
  * Dependency CVE watch across your lockfiles
  * Regression alerts the moment new findings appear
  * Monthly PDF baseline report for your team/investors

{payment_lines('monitoring')}

Baseline sample and methodology: {DOCS_URL}

- {sender_name}, NanoClone Systems Ltd.
  You receive this because you committed to {repo}. One email; no follow-ups unless you reply.
"""
    return subject, body, _email_html("monitoring", lead, scan)


# ==================== SOCIAL (short-form) ====================

def social_reply(lead: dict, scan: dict) -> str:
    """Short Farcaster reply — proof teaser + offer, fits 1024 bytes."""
    rating = risk_rating(scan)
    repo = lead.get("repo") or lead.get("full_name") or "your repo"
    findings = top_findings(scan, 1)
    teaser = ""
    if findings:
        f0 = findings[0]
        cwe = f0.get("cwe") or f0.get("cve") or ""
        teaser = (f"Top hit: [{(f0.get('severity') or '').upper()}] "
                  f"{f0.get('type', 'finding')} {cwe}"
                  + (f" @ line {f0['line_number']}" if f0.get("line_number") else ""))
    else:
        teaser = "No actionable findings in the current tree."
    return (
        f"Ran our engine on {repo}: {rating} rating.\n"
        f"{teaser}\n"
        f"Disclosure is free; verified patch + signed PDF is {PRICE_REMEDIATION}, "
        f"monitoring {PRICE_RETAINER}."
    )


# ==================== DISPATCH ====================

def build_email(playbook: str, lead: dict, scan: dict) -> tuple[str, str, str]:
    if playbook == "remediation":
        return remediation_email(lead, scan)
    return monitoring_email(lead, scan)


if __name__ == "__main__":
    demo_repo = {
        "full_name": "acme-dao/contracts", "stargazers_count": 340,
        "homepage": "https://acme.dao", "topics": ["defi", "solidity"],
        "description": "Production DeFi protocol settlement layer",
        "pushed_at": "2026-09-27T10:00:00Z", "license": {"spdx_id": "MIT"},
    }
    demo_scan = {
        "sast_findings": [
            {"type": "COMMAND_INJECTION", "severity": "CRITICAL", "cwe": "CWE-78",
             "description": "User input reaches os.system().", "line_number": 42,
             "line_content": "os.system('git clone ' + user_url)"},
            {"type": "XSS", "severity": "HIGH", "cwe": "CWE-79",
             "description": "innerHTML written with unsanitized input.",
             "line_number": 88, "line_content": "el.innerHTML = query;"},
        ],
        "sca_findings": [],
    }
    print("ICP score:", score_repo(demo_repo), "| qualifies:", qualifies(demo_repo))
    print("playbook:", pick_playbook(demo_scan))
    print("risk:", risk_rating(demo_scan))
    print("=" * 60)

    import pathlib
    out = pathlib.Path(__file__).resolve().parent.parent / "reports"
    out.mkdir(exist_ok=True)
    banned = ("$0.01", "$0.50", "$5.00", "pip install x402", "micro-audit",
              "MCP Manifest", "quick-scan")

    lead = {"name": "Jane Dev", "repo": demo_repo["full_name"]}
    clean_scan = {"sast_findings": [], "sca_findings": []}
    for kind, scan in (("remediation", demo_scan), ("monitoring", clean_scan)):
        subj, body, html_body = build_email(kind, lead, scan)
        blob = subj + body + html_body
        hits = [t for t in banned if t in blob]
        print(f"{kind}: subject={subj!r} | text={len(body)}B html={len(html_body)}B "
              f"| ACSA tokens: {hits or 'none'}")
        print("  stripe CTA: " + ("present" if "buy.stripe.com" in html_body else "MISSING"))
        (out / f"demo_{kind}_email.html").write_text(html_body, encoding="utf-8")
        assert not hits, hits
        assert "pyresec.png" in html_body and "nanoclone.png" in html_body

    print("=" * 60)
    print("SOCIAL:\n" + social_reply({"repo": demo_repo["full_name"]}, demo_scan))
