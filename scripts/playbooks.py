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
from typing import Optional

# ==================== PRICING & RAILS ====================

PRICE_REMEDIATION = os.getenv("PRICE_REMEDIATION", "$750")
PRICE_RETAINER = os.getenv("PRICE_RETAINER", "$495/mo")
STRIPE_REMEDIATION = os.getenv("STRIPE_LINK_REMEDIATION", "")
STRIPE_RETAINER = os.getenv("STRIPE_LINK_RETAINER", "")
DOCS_URL = os.getenv("PYRESEC_DOCS_URL",
                     "https://pyresec-agent-519576377065.us-central1.run.app/docs")

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


# ==================== COPY: REMEDIATION (proof-led, one-time) ====================

def remediation_subject(lead: dict) -> str:
    repo = lead.get("repo") or lead.get("full_name") or "your repo"
    return f"Security finding in {repo} - proof attached"


def remediation_email(lead: dict, scan: dict, sender_name: str = "PYRESEC") -> tuple[str, str]:
    """Returns (subject, text_body). Finding-first, free disclosure, paid fix."""
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
    return subject, body


# ==================== COPY: MONITORING (recurring retainer) ====================

def monitoring_subject(lead: dict) -> str:
    repo = lead.get("repo") or lead.get("full_name") or "your repo"
    return f"{repo}: security baseline ready (weekly monitoring available)"


def monitoring_email(lead: dict, scan: dict, sender_name: str = "PYRESEC") -> tuple[str, str]:
    """Returns (subject, text_body). Baseline result + recurring watch offer."""
    repo = lead.get("repo") or lead.get("full_name") or "your repository"
    name = (lead.get("name") or "").split()[0:1]
    hi = f"Hi {name[0]}," if name else "Hi,"
    rating = risk_rating(scan)
    proof = proof_summary(scan, 3)
    counts = {}
    for f in (scan.get("sast_findings") or []) + (scan.get("sca_findings") or []):
        sev = (f.get("severity") or "?").upper()
        counts[sev] = counts.get(sev, 0) + 1
    count_str = ", ".join(f"{v} {k.lower()}" for k, v in counts.items()) or "clean"

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
    return subject, body


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

def build_email(playbook: str, lead: dict, scan: dict) -> tuple[str, str]:
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
    subj, body = build_email("remediation", {"name": "Jane Dev", "repo": demo_repo["full_name"]}, demo_scan)
    print("SUBJECT:", subj)
    print(body)
    print("=" * 60)
    print("SOCIAL:\n" + social_reply({"repo": demo_repo["full_name"]}, demo_scan))
