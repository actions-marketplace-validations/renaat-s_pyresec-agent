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

# Windows console: allow unicode in names/subjects (CMD defaults to cp1252)
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import playbooks
import probe
import revenue_ledger
import telegram_app

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

# Audit log for daily runs (timestamp, qualified count, skip reasons, etc.)
RUNS_LOG_FILE = "scripts/.outreach_runs.json"

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


def _clean_domain(raw: str) -> str:
    """Strip protocol/path/www from a URL to get a clean apex-style domain."""
    domain = raw.replace("https://", "").replace("http://", "").split("/")[0].lower()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def get_org_contact(repo: dict) -> Optional[dict]:
    """Find the best high-ticket contact for an organization-owned repo.

    Priority:
      1. Public email on the GitHub organization profile.
      2. security@<domain> derived from the org's website/blog.
      3. security@<domain> derived from the repo homepage.
    """
    org = repo.get("owner", {}) or {}
    org_login = org.get("login", "")
    if not org_login:
        return None

    org_email = ""
    org_name = org_login
    try:
        url = f"https://api.github.com/orgs/{org_login}"
        with httpx.Client(timeout=20.0) as client:
            resp = client.get(url, headers=github_headers())
            if resp.status_code == 200:
                data = resp.json()
                org_email = (data.get("email") or "").strip()
                org_name = data.get("name") or org_login
                blog = (data.get("blog") or "").strip()
                if org_email:
                    return {"name": org_name, "email": org_email, "source": "org_profile"}
                if blog:
                    domain = _clean_domain(blog)
                    if domain and "." in domain:
                        return {"name": org_name, "email": f"security@{domain}", "source": "derived"}
    except Exception:
        pass

    homepage = (repo.get("homepage") or "").strip()
    if homepage:
        domain = _clean_domain(homepage)
        if domain and "." in domain:
            return {"name": org_name, "email": f"security@{domain}", "source": "derived"}

    return None


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


def log_run(summary: dict):
    """Append a run summary to the audit log (last 100 runs kept)."""
    runs = []
    if os.path.exists(RUNS_LOG_FILE):
        try:
            with open(RUNS_LOG_FILE, "r", encoding="utf-8") as f:
                runs = json.load(f)
        except Exception:
            runs = []
    runs.append(summary)
    with open(RUNS_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(runs[-100:], f, indent=2, ensure_ascii=False)


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


# ==================== BATCH DISPATCH (Telegram-gated) ====================

def dispatch_batch(batch: list[dict], direct: bool = False) -> int:
    """Send immediately (--direct / OUTREACH_DIRECT) or gate behind ONE Telegram tap."""
    import telegram_app

    if not batch:
        return 0

    if os.getenv("OUTREACH_DIRECT", "").lower() in ("1", "true", "yes"):
        direct = True

    if direct or not telegram_app.configured():
        sent = 0
        for item in batch:
            if send_email(item["to"], item["subject"], item["body"], item.get("html")):
                sent += 1
                revenue_ledger.record(item["playbook"], "proof_sent", 0,
                                      item["repo"], "email")
                print(f"  [SENT] {item['repo']} -> {item['to']}")
            else:
                print(f"  [FAILED] {item['repo']}")
            time.sleep(RESEND_API_DELAY)
        return sent

    # One Telegram message, one tap for the whole batch
    import social_scanner

    qid = f"email-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    n_rem = sum(1 for i in batch if i["playbook"] == "remediation")
    n_mon = len(batch) - n_rem
    summary_line = (f"{len(batch)} qualified leads | "
                    f"{n_rem} remediation, {n_mon} monitoring")

    lines = []
    for item in batch[:35]:
        tag = item["playbook"][:4].upper()
        lines.append(f"{item['repo']}  [{tag}] {item['rating']} "
                     f"{item['findings']}f -> {item['to']}")
    if len(batch) > 35:
        lines.append(f"... and {len(batch) - 35} more")

    header = f"📧 OUTREACH BATCH\n{summary_line}"
    msg_id = telegram_app.send_lead(header, "\n".join(lines), qid)

    queue = social_scanner.load_queue()
    queue.append({
        "qid": qid, "kind": "email_batch", "status": "pending",
        "tg_message_id": msg_id, "emails": batch, "summary": summary_line,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    social_scanner.save_queue(queue)
    print(f"  [GATE] batch queued for Telegram approval (qid={qid}, {len(batch)} emails)")
    return 0


# ==================== MAIN PIPELINE ====================

def run_scraper(dry_run: bool = False, max_repos: int = 30, direct: bool = False):
    """Main scraper pipeline."""
    print("=" * 60)
    print("  PYRESEC Git Scraper — High-Ticket Outreach (proof-led)")
    print("=" * 60)
    print()

    date_threshold = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    seen = load_seen_repos()
    contacted = 0
    skipped_counts = {
        "seen": 0,
        "user": 0,
        "fork": 0,
        "archived": 0,
        "icp": 0,
        "no_contact": 0,
        "no_code": 0,
    }
    searches = 0
    batch: list[dict] = []

    for query_config in SEARCH_QUERIES:
        if len(batch) >= max_repos:
            break
        query = query_config["query"].format(date=date_threshold)
        label = query_config["label"]
        print(f"[SEARCH] {label}: {query[:60]}...")
        searches += 1

        repos = search_repos(query, per_page=10)
        time.sleep(GITHUB_API_DELAY)

        for repo in repos:
            if len(batch) >= max_repos:
                print(f"\n[DONE] Reached max_repos limit ({max_repos})")
                break

            full_name = repo["full_name"]
            repo_url = repo["html_url"]

            # Deduplication
            if full_name in seen:
                skipped_counts["seen"] += 1
                continue

            print(f"  Checking {full_name}...")

            # --- High-ticket filters: enterprise buyers only ---
            owner_type = repo.get("owner", {}).get("type", "")
            if owner_type != "Organization":
                print(f"    [SKIP] owner type '{owner_type}' — not an organization")
                seen.add(full_name)
                skipped_counts["user"] += 1
                continue
            if repo.get("fork"):
                print(f"    [SKIP] fork")
                seen.add(full_name)
                skipped_counts["fork"] += 1
                continue
            if repo.get("archived"):
                print(f"    [SKIP] archived")
                seen.add(full_name)
                skipped_counts["archived"] += 1
                continue

            # --- ICP qualification (funded-team heuristic) ---
            score = playbooks.score_repo(repo)
            if score < playbooks.ICP_MIN_SCORE:
                print(f"    [ICP] score {score} below {playbooks.ICP_MIN_SCORE} - not a target")
                seen.add(full_name)
                skipped_counts["icp"] += 1
                continue

            # Find the organization's security contact (no individual dev emails)
            contact = get_org_contact(repo)
            time.sleep(GITHUB_API_DELAY)

            if not contact:
                print(f"    [SKIP] No organization contact found")
                seen.add(full_name)
                skipped_counts["no_contact"] += 1
                continue

            email = contact["email"]
            print(f"    Contact: {email} ({contact['source']})")

            # Generic greeting for corporate mailboxes (security@, contact@, etc.)
            name = "there"

            # --- Free proof: fetch entry file + local scan ---
            code = probe.fetch_repo_main_file(full_name)
            if not code:
                print(f"    [PROOF] no scannable entry file - skip")
                seen.add(full_name)
                skipped_counts["no_code"] += 1
                continue

            scan = probe.local_scan(code)
            playbook = playbooks.pick_playbook(scan)
            rating = playbooks.risk_rating(scan)
            lead = {"name": name, "email": email, "repo": full_name, "repo_url": repo_url}
            subject, body, html_body = playbooks.build_email(playbook, lead, scan)
            print(f"    [ICP] {score} | proof: {scan['total_findings']} finding(s) "
                  f"({rating}) | playbook: {playbook}")

            batch.append({
                "to": email, "subject": subject, "body": body, "html": html_body,
                "repo": full_name, "playbook": playbook,
                "score": score, "rating": rating,
                "findings": scan["total_findings"],
            })

            if dry_run:
                print(f"    [DRY RUN] would queue -> {email}")
                print(f"      subject: {subject}")
                print(f"      body preview: {body[:220].strip()}...")

            seen.add(full_name)

    # Save dedup state (dry-run must not pollute the production dedup list)
    if dry_run:
        print("\n[DRY RUN] not updating seen-repos dedup file")
    else:
        save_seen_repos(seen)

    if dry_run:
        print(f"\n[DRY RUN] {len(batch)} qualified email(s) built — nothing sent")
    elif batch:
        contacted = dispatch_batch(batch, direct=direct)

    skipped_total = sum(skipped_counts.values())
    run_ts = datetime.now(timezone.utc).isoformat()

    summary = {
        "timestamp": run_ts,
        "dry_run": dry_run,
        "max_repos": max_repos,
        "icp_min_score": playbooks.ICP_MIN_SCORE,
        "searches": searches,
        "qualified": len(batch),
        "sent_or_queued": contacted,
        "skipped": skipped_counts,
        "skipped_total": skipped_total,
        "seen_total": len(seen),
        "batch_queued": bool(batch) and not dry_run and not os.getenv("OUTREACH_DIRECT", "").lower() in ("1", "true", "yes") and telegram_app.configured(),
    }
    log_run(summary)

    # Always notify Telegram so leads never "silently" disappear
    if telegram_app.configured():
        status_emoji = "🟢" if batch else "🔵"
        lines = [
            f"{status_emoji} PYRESEC Outreach Run — {run_ts[:10]}",
            f"Qualified leads: {len(batch)} | Sent/queued: {contacted}",
            f"Skipped: {skipped_total} (seen {skipped_counts['seen']}, user {skipped_counts['user']}, ICP {skipped_counts['icp']}, no contact {skipped_counts['no_contact']}, no code {skipped_counts['no_code']})",
            f"ICP floor: {playbooks.ICP_MIN_SCORE} | Searches run: {searches}",
        ]
        if batch and not dry_run:
            lines.append("A batch was queued in Telegram for approval.")
        elif not batch:
            lines.append("No new qualified org leads matched today's searches.")
        try:
            telegram_app.notify("\n".join(lines))
        except Exception as e:
            print(f"  [TELEGRAM NOTIFY ERROR] {e}")

    print()
    print("=" * 60)
    print(f"  Complete. Qualified: {len(batch)} | Sent/queued: {contacted} | Skipped (seen): {skipped_total}")
    print("=" * 60)


# ==================== ENTRY POINT ====================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PYRESEC Git Scraper")
    parser.add_argument("--dry-run", action="store_true", help="Preview without sending emails")
    parser.add_argument("--max-repos", type=int, default=30, help="Max repos to contact per run")
    parser.add_argument("--direct", action="store_true",
                        help="Send immediately instead of gating via Telegram")
    args = parser.parse_args()

    if not RESEND_API_KEY and not args.dry_run:
        print("WARNING: RESEND_API_KEY not set. Emails will not be sent.")
        print("Set it in your environment or .env file.")
        print()

    run_scraper(dry_run=args.dry_run, max_repos=args.max_repos, direct=args.direct)
