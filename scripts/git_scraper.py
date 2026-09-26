#!/usr/bin/env python3
"""
PYRESEC Git Scraper — Automated Outbound Lead Generation

Scans GitHub for recently pushed repos containing Web3 configs or FastAPI
infrastructure, extracts author emails from commits, and sends cold
outreach via Resend.

Usage:
    python scripts/git_scraper.py
    python scripts/git_scraper.py --dry-run
    python scripts/git_scraper.py --max-repos 20

Environment Variables:
    GITHUB_TOKEN        — GitHub personal access token (optional, raises rate limit)
    RESEND_API_KEY      — Resend API key for email delivery
    PYRESEC_URL         — PYRESEC API base URL (default: production)
    PYRESEC_SENDER      — Verified sender email in Resend (default: onboarding@resend.dev)
    DRY_RUN             — Set to "true" to preview without sending emails
"""

import os
import sys
import json
import time
import argparse
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

# ==================== CONFIGURATION ====================

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")  # Optional but recommended — raises rate limit from 10 to 30 req/min
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
PYRESEC_URL = os.getenv(
    "PYRESEC_URL",
    "https://pyresec-agent-519576377065.us-central1.run.app"
)
PYRESEC_SENDER = os.getenv("PYRESEC_SENDER", "onboarding@resend.dev")
PYRESEC_FROM_NAME = os.getenv("PYRESEC_FROM_NAME", "PYRESEC Agent")

# GitHub Search queries — repos pushed recently with target tech stacks
# Uses keyword searches (filename: syntax doesn't combine well with pushed:)
SEARCH_QUERIES = [
    # Web3 / Smart Contracts
    {"query": "foundry solidity pushed:>={date}", "type": "web3", "label": "Foundry/Solidity"},
    {"query": "hardhat ethereum pushed:>={date}", "type": "web3", "label": "Hardhat/Ethereum"},
    {"query": "solidity smart contract pushed:>={date}", "type": "web3", "label": "Solidity Contract"},
    {"query": "web3.py blockchain pushed:>={date}", "type": "web3", "label": "Web3.py"},
    {"query": "smart contract deployment pushed:>={date}", "type": "web3", "label": "Contract Deploy"},
    {"query": "erc20 token pushed:>={date}", "type": "web3", "label": "ERC20 Token"},
    {"query": "defi protocol pushed:>={date}", "type": "web3", "label": "DeFi Protocol"},
    {"query": "base mainnet pushed:>={date}", "type": "web3", "label": "Base Mainnet"},
    {"query": "nft contract solidity pushed:>={date}", "type": "web3", "label": "NFT Contract"},
    {"query": "solidity audit pushed:>={date}", "type": "web3", "label": "Solidity Audit"},
    {"query": "ethers.js hardhat pushed:>={date}", "type": "web3", "label": "Ethers.js"},
    {"query": "vyper contract pushed:>={date}", "type": "web3", "label": "Vyper Contract"},
    {"query": "rust solana program pushed:>={date}", "type": "web3", "label": "Solana Rust"},
    {"query": "move aptos smart contract pushed:>={date}", "type": "web3", "label": "Move/Aptos"},
    # Backend / FastAPI
    {"query": "fastapi language:python pushed:>={date}", "type": "fastapi", "label": "FastAPI"},
    {"query": "fastapi uvicorn pushed:>={date}", "type": "fastapi", "label": "FastAPI Uvicorn"},
    {"query": "django rest framework pushed:>={date}", "type": "fastapi", "label": "Django DRF"},
    {"query": "flask api pushed:>={date}", "type": "fastapi", "label": "Flask API"},
    {"query": "express node api pushed:>={date}", "type": "fastapi", "label": "Express API"},
    {"query": "next.js api routes pushed:>={date}", "type": "fastapi", "label": "Next.js API"},
    {"query": "graphql api server pushed:>={date}", "type": "fastapi", "label": "GraphQL API"},
    # General security-interest targets
    {"query": "authentication jwt security pushed:>={date}", "type": "fastapi", "label": "Auth/JWT"},
    {"query": "payment stripe integration pushed:>={date}", "type": "fastapi", "label": "Payments"},
    {"query": "docker kubernetes deploy pushed:>={date}", "type": "fastapi", "label": "DevOps"},
]

# Deduplication file
SEEN_REPOS_FILE = "scripts/.seen_repos.json"

# Rate limiting
GITHUB_API_DELAY = 2.0  # seconds between GitHub API calls (unauthenticated: 10/min)
RESEND_API_DELAY = 0.5  # seconds between emails


# ==================== GITHUB API ====================

def github_headers() -> dict:
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return headers


def search_repos(query: str, per_page: int = 10) -> list[dict]:
    """Search GitHub for recently pushed repos matching a query."""
    url = "https://api.github.com/search/repositories"
    params = {
        "q": query,
        "sort": "updated",
        "order": "desc",
        "per_page": per_page,
    }

    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, headers=github_headers(), params=params)

        if resp.status_code == 403:
            print(f"  [RATE LIMITED] GitHub API rate limit hit. Waiting 60s...")
            time.sleep(60)
            resp = client.get(url, headers=github_headers(), params=params)

        if resp.status_code != 200:
            print(f"  [ERROR] GitHub search returned {resp.status_code}: {resp.text[:200]}")
            return []

        data = resp.json()
        return data.get("items", [])


def get_commit_author(repo_full_name: str, since: str) -> Optional[dict]:
    """Get the most recent commit author email for a repo."""
    url = f"https://api.github.com/repos/{repo_full_name}/commits"
    params = {"since": since, "per_page": 1}

    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, headers=github_headers(), params=params)

        if resp.status_code != 200:
            return None

        commits = resp.json()
        if not commits:
            return None

        commit = commits[0]
        author = commit.get("commit", {}).get("author", {})
        email = author.get("email", "")

        # Skip noreply emails
        if not email or "noreply" in email or "users.noreply" in email:
            return None

        return {
            "name": author.get("name", ""),
            "email": email,
            "date": author.get("date", ""),
            "message": commit.get("commit", {}).get("message", "")[:100],
        }


def load_seen_repos() -> set:
    """Load previously contacted repos to avoid duplicates."""
    if os.path.exists(SEEN_REPOS_FILE):
        with open(SEEN_REPOS_FILE, "r") as f:
            data = json.load(f)
            return set(data.get("repos", []))
    return set()


def save_seen_repos(seen: set):
    """Save contacted repos."""
    with open(SEEN_REPOS_FILE, "w") as f:
        json.dump({"repos": list(seen), "updated": datetime.now(timezone.utc).isoformat()}, f, indent=2)


# ==================== EMAIL TEMPLATES ====================

def build_email_body(repo_name: str, repo_url: str, file_type: str) -> str:
    """Build a short, text-only developer outreach email."""
    return f"""Hey,

Noticed you just pushed a new project to GitHub ({repo_name}).

If you want a high-speed security check without creating an account or managing API keys, you can stream a micro-audit straight to your terminal.

Run it instantly via the x402 protocol client:

pip install x402
x402 run {PYRESEC_URL}/v1/audit/quick-scan --data '{{"code": "<your-code-here>"}}'

Cost: $0.01 USDC on Base Mainnet (auto-handled by your local wallet).
Output: Top 3 vulnerability findings, CWE IDs, and line-number pinpointing.

Deep Audits ($0.50) and Auto-Remediation patches ($5.00) are also supported natively.

Docs: {PYRESEC_URL}/docs
MCP Manifest for IDE Agents: {PYRESEC_URL}/mcp/manifest.json

— PYRESEC Agent
NanoClone Systems Ltd.
"""


def build_email_subject(repo_name: str, file_type: str) -> str:
    """Build a compelling subject line."""
    if file_type == "fastapi":
        return f"Quick security check for {repo_name}?"
    return f"Security audit for your {repo_name} contract?"


def build_email_html(repo_name: str, file_type: str) -> str:
    """Build HTML email with embedded logos for professional presentation."""
    logo_base = f"{PYRESEC_URL}/static"

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
    <p style="color:#ccc;font-size:15px;margin:0 0 16px;text-align:center;">Hey,</p>
    <p style="color:#ccc;font-size:15px;margin:0 0 20px;text-align:center;">Noticed you just pushed a new project to GitHub (<a href="https://github.com/{repo_name}" style="color:#dc2626;">{repo_name}</a>).</p>
    <p style="color:#ccc;font-size:15px;margin:0 0 20px;text-align:center;">If you want a high-speed security check <strong style="color:#fff;">without creating an account or managing API keys</strong>, you can stream a micro-audit straight to your terminal.</p>
    <p style="color:#ccc;font-size:15px;margin:0 0 16px;text-align:center;">Run it instantly via the x402 protocol client:</p>

    <!-- Code Block -->
    <table width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 28px;"><tr><td style="background:rgba(255,255,255,0.04);border-radius:12px;border:2px solid rgba(255,255,255,0.3);padding:24px 28px;">
      <code style="color:#22c55e;font-family:'SF Mono',Consolas,monospace;font-size:15px;white-space:pre-wrap;display:block;text-align:center;">pip install x402
x402 run {PYRESEC_URL}/v1/audit/quick-scan \\
  --data '{{"code": "&lt;your-code-here&gt;"}}'</code>
    </td></tr></table>

    <!-- Cost & Output -->
    <table width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 28px;">
      <tr>
        <td style="background:rgba(255,255,255,0.04);border-radius:12px;border:2px solid rgba(255,255,255,0.3);padding:24px 28px;">
          <table width="100%" cellpadding="0" cellspacing="0"><tr>
            <td style="padding-right:24px;vertical-align:middle;text-align:center;"><span style="color:#22c55e;font-size:32px;font-weight:800;">$0.01</span><br><span style="color:#888;font-size:13px;">USDC on Base</span></td>
            <td style="border-left:2px solid rgba(255,255,255,0.3);padding-left:24px;vertical-align:middle;"><span style="color:#ccc;font-size:14px;text-align:center;">Top 3 vulnerability findings<br>CWE IDs + line-number pinpointing</span></td>
          </tr></table>
        </td>
      </tr>
    </table>

    <!-- Pricing Tiers -->
    <table width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 28px;">
      <tr>
        <td style="background:rgba(255,255,255,0.04);border-radius:12px;border:2px solid rgba(255,255,255,0.3);padding:24px;text-align:center;width:33%;">
          <div style="color:#22c55e;font-size:28px;font-weight:800;">$0.01</div>
          <div style="color:#999;font-size:14px;margin-top:6px;letter-spacing:1px;">Quick Scan</div>
        </td>
        <td style="width:10px;"></td>
        <td style="background:rgba(255,255,255,0.04);border-radius:12px;border:2px solid rgba(255,255,255,0.3);padding:24px;text-align:center;width:33%;">
          <div style="color:#eab308;font-size:28px;font-weight:800;">$0.50</div>
          <div style="color:#999;font-size:14px;margin-top:6px;letter-spacing:1px;">Deep Audit</div>
        </td>
        <td style="width:10px;"></td>
        <td style="background:rgba(255,255,255,0.04);border-radius:12px;border:2px solid rgba(255,255,255,0.3);padding:24px;text-align:center;width:33%;">
          <div style="color:#dc2626;font-size:28px;font-weight:800;">$5.00</div>
          <div style="color:#999;font-size:14px;margin-top:6px;letter-spacing:1px;">Auto-Remediation</div>
        </td>
      </tr>
    </table>

    <p style="color:#888;font-size:14px;margin:0 0 24px;text-align:center;">Deep Audits and Auto-Remediation patches are also supported natively via the x402 client.</p>

    <!-- Links -->
    <p style="margin:0;text-align:center;"><a href="{PYRESEC_URL}/docs" style="color:#dc2626;font-size:14px;text-decoration:none;">Documentation</a> <span style="color:#444;">&nbsp;&nbsp;|&nbsp;&nbsp;</span> <a href="{PYRESEC_URL}/mcp/manifest.json" style="color:#dc2626;font-size:14px;text-decoration:none;">MCP Manifest for IDE Agents</a></p>
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


# ==================== RESEND EMAIL ====================

def send_email(to_email: str, subject: str, body: str, html: str = None) -> bool:
    """Send an email via Resend API. Supports HTML with embedded logos."""
    if not RESEND_API_KEY:
        print("  [SKIP] RESEND_API_KEY not set — cannot send emails")
        return False

    url = "https://api.resend.com/emails"
    headers = {
        "Authorization": f"Bearer {RESEND_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "from": f"{PYRESEC_FROM_NAME} <{PYRESEC_SENDER}>",
        "to": [to_email],
        "subject": subject,
        "text": body,
    }
    if html:
        payload["html"] = html

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, headers=headers, json=payload)

        if resp.status_code == 200 or resp.status_code == 201:
            return True
        else:
            print(f"  [EMAIL ERROR] {resp.status_code}: {resp.text[:200]}")
            return False


# ==================== MAIN PIPELINE ====================

def run_scraper(dry_run: bool = False, max_repos: int = 30):
    """Main scraper pipeline."""
    print("=" * 60)
    print("  PYRESEC Git Scraper — Outbound Lead Generation")
    print("=" * 60)
    print()

    date_threshold = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    seen = load_seen_repos()
    contacted = 0
    skipped = 0

    for query_config in SEARCH_QUERIES:
        query = query_config["query"].format(date=date_threshold)
        file_type = query_config["type"]
        label = query_config["label"]
        print(f"[SEARCH] {label}: {query[:60]}...")

        repos = search_repos(query, per_page=10)
        time.sleep(GITHUB_API_DELAY)

        for repo in repos:
            if contacted >= max_repos:
                print(f"\n[DONE] Reached max_repos limit ({max_repos})")
                break

            full_name = repo["full_name"]
            repo_url = repo["html_url"]

            # Deduplication
            if full_name in seen:
                skipped += 1
                continue

            # Get commit author email
            print(f"  Checking {full_name}...")
            since = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%dT00:00:00Z")
            author = get_commit_author(full_name, since)
            time.sleep(GITHUB_API_DELAY)

            if not author:
                print(f"    [SKIP] No public author email found")
                seen.add(full_name)
                continue

            email = author["email"]
            name = author["name"]
            print(f"    Author: {name} <{email}>")

            # Build email
            subject = build_email_subject(repo["name"], file_type)
            body = build_email_body(full_name, repo_url, file_type)
            html = build_email_html(full_name, file_type)

            if dry_run:
                print(f"    [DRY RUN] Would send to {email}")
                print(f"    Subject: {subject}")
            else:
                print(f"    Sending to {email}...")
                success = send_email(email, subject, body, html=html)
                if success:
                    print(f"    [SENT] Email delivered")
                    contacted += 1
                else:
                    print(f"    [FAILED] Email not sent")
                time.sleep(RESEND_API_DELAY)

            seen.add(full_name)

    # Save dedup state
    save_seen_repos(seen)

    print()
    print("=" * 60)
    print(f"  Complete. Contacted: {contacted} | Skipped (seen): {skipped}")
    print("=" * 60)


# ==================== ENTRY POINT ====================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PYRESEC Git Scraper")
    parser.add_argument("--dry-run", action="store_true", help="Preview without sending emails")
    parser.add_argument("--max-repos", type=int, default=30, help="Max repos to contact per run")
    args = parser.parse_args()

    if not RESEND_API_KEY and not args.dry_run:
        print("WARNING: RESEND_API_KEY not set. Emails will not be sent.")
        print("Set it in your environment or .env file.")
        print()

    run_scraper(dry_run=args.dry_run, max_repos=args.max_repos)
