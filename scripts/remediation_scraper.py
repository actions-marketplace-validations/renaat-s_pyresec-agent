#!/usr/bin/env python3
"""
PYRESEC Remediation Scraper — Dedicated high-ticket remediation lead engine.

Finds organization-owned repos that already show security findings (CRITICAL/HIGH
via local SAST/SCA), extracts org security contacts, and queues proof-led
remediation outreach ($750 one-time) for Telegram approval.

This engine is separate from the monitoring scraper so each can be tuned
independently.

Usage:
    python scripts/remediation_scraper.py
    python scripts/remediation_scraper.py --dry-run
    python scripts/remediation_scraper.py --max-repos 20
"""

import os
import sys
import json
import time
import argparse
from datetime import datetime, timedelta, timezone

import httpx
from dotenv import load_dotenv

load_dotenv()

# Windows console unicode
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import playbooks
import probe
import telegram_app
import social_scanner

# Re-use the low-level helpers from the monitoring scraper
from git_scraper import (
    github_headers,
    search_repos,
    get_org_contact,
    load_seen_repos,
    save_seen_repos,
    dispatch_batch,
    SEEN_REPOS_FILE,
    GITHUB_API_DELAY,
)

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
PYRESEC_FROM_NAME = os.getenv("PYRESEC_FROM_NAME", "PYRESEC Agent")
PYRESEC_SENDER = os.getenv("PYRESEC_SENDER", "onboarding@resend.dev")

# Remediation engine can use a lower ICP floor than monitoring — a repo with
# visible findings is worth contacting even if its star count is modest.
REMEDIATION_ICP_MIN_SCORE = int(os.getenv("REMEDIATION_ICP_MIN_SCORE", playbooks.ICP_MIN_SCORE))

# Audit log
RUNS_LOG_FILE = "scripts/.remediation_runs.json"

# Remediation-specific search queries — target repos with a higher probability of
# existing vulnerabilities or active security work.
SEARCH_QUERIES_REMEDIATION = [
    # Smart-contract vulnerability signals
    {"query": "reentrancy solidity pushed:>={date}", "label": "Reentrancy"},
    {"query": "access control solidity bug pushed:>={date}", "label": "Access Control"},
    {"query": "integer overflow solidity pushed:>={date}", "label": "Integer Overflow"},
    {"query": "unchecked call solidity pushed:>={date}", "label": "Unchecked Calls"},
    {"query": "flash loan attack pushed:>={date}", "label": "Flash Loan"},
    {"query": "smart contract exploit pushed:>={date}", "label": "Exploit History"},
    {"query": "smart contract audit findings pushed:>={date}", "label": "Audit Findings"},
    {"query": "defi hack post mortem pushed:>={date}", "label": "DeFi Hack"},
    {"query": "hardhat test security pushed:>={date}", "label": "Hardhat Security"},
    {"query": "foundry fuzz test failure pushed:>={date}", "label": "Fuzz Failures"},
    # Backend / Web2 vulnerability signals
    {"query": "sql injection python pushed:>={date}", "label": "SQL Injection"},
    {"query": "xss vulnerability javascript pushed:>={date}", "label": "XSS"},
    {"query": "jwt authentication bypass pushed:>={date}", "label": "Auth Bypass"},
    {"query": "command injection python pushed:>={date}", "label": "Command Injection"},
    {"query": "path traversal vulnerability pushed:>={date}", "label": "Path Traversal"},
    {"query": "insecure deserialization pushed:>={date}", "label": "Deserialization"},
    {"query": "hardcoded secrets detection pushed:>={date}", "label": "Hardcoded Secrets"},
    {"query": "cve dependency alert pushed:>={date}", "label": "CVE Alert"},
]


def log_run(summary: dict):
    """Append a run summary to the remediation audit log (last 100 runs)."""
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


def run_remediation_scraper(dry_run: bool = False, max_repos: int = 20):
    """Main remediation lead pipeline."""
    print("=" * 60)
    print("  PYRESEC Remediation Scraper — High-Ticket Fix Leads")
    print("=" * 60)
    print()

    date_threshold = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    seen = load_seen_repos()
    skipped_counts = {
        "seen": 0, "user": 0, "fork": 0, "archived": 0,
        "icp": 0, "no_contact": 0, "no_code": 0, "clean": 0,
    }
    searches = 0
    batch = []

    for query_config in SEARCH_QUERIES_REMEDIATION:
        if len(batch) >= max_repos:
            break
        query = query_config["query"].format(date=date_threshold)
        label = query_config["label"]
        print(f"[SEARCH] {label}: {query[:60]}...")
        searches += 1

        repos = search_repos(query, per_page=15)
        time.sleep(GITHUB_API_DELAY)

        for repo in repos:
            if len(batch) >= max_repos:
                print(f"\n[DONE] Reached max_repos limit ({max_repos})")
                break

            full_name = repo["full_name"]
            repo_url = repo["html_url"]

            if full_name in seen:
                skipped_counts["seen"] += 1
                continue

            print(f"  Checking {full_name}...")

            owner_type = repo.get("owner", {}).get("type", "")
            if owner_type != "Organization":
                print(f"    [SKIP] owner type '{owner_type}'")
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

            score = playbooks.score_repo(repo)
            if score < REMEDIATION_ICP_MIN_SCORE:
                print(f"    [ICP] score {score} below {REMEDIATION_ICP_MIN_SCORE}")
                seen.add(full_name)
                skipped_counts["icp"] += 1
                continue

            contact = get_org_contact(repo)
            time.sleep(GITHUB_API_DELAY)
            if not contact:
                print(f"    [SKIP] No organization contact found")
                seen.add(full_name)
                skipped_counts["no_contact"] += 1
                continue

            email = contact["email"]
            print(f"    Contact: {email} ({contact['source']})")

            code = probe.fetch_repo_main_file(full_name)
            if not code:
                print(f"    [PROOF] no scannable entry file")
                seen.add(full_name)
                skipped_counts["no_code"] += 1
                continue

            scan = probe.local_scan(code)
            playbook = playbooks.pick_playbook(scan)
            rating = playbooks.risk_rating(scan)

            # Remediation engine: only queue when there are real findings to fix
            if playbook != "remediation":
                print(f"    [CLEAN] rating {rating} — no CRITICAL/HIGH findings; skip")
                seen.add(full_name)
                skipped_counts["clean"] += 1
                continue

            print(f"    [REMEDIATION] {score} | proof: {scan['total_findings']} finding(s) "
                  f"({rating}) | playbook: {playbook}")

            lead = {"name": "there", "email": email, "repo": full_name, "repo_url": repo_url}
            subject, body, html_body = playbooks.build_email("remediation", lead, scan)

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

    if dry_run:
        print("\n[DRY RUN] not updating seen-repos dedup file")
    else:
        save_seen_repos(seen)

    contacted = 0
    if not dry_run and batch:
        contacted = dispatch_batch(batch, direct=False)

    skipped_total = sum(skipped_counts.values())
    run_ts = datetime.now(timezone.utc).isoformat()
    summary = {
        "timestamp": run_ts,
        "dry_run": dry_run,
        "max_repos": max_repos,
        "icp_min_score": REMEDIATION_ICP_MIN_SCORE,
        "searches": searches,
        "qualified": len(batch),
        "sent_or_queued": contacted,
        "skipped": skipped_counts,
        "skipped_total": skipped_total,
        "seen_total": len(seen),
        "batch_queued": bool(batch) and not dry_run and telegram_app.configured(),
    }
    log_run(summary)

    if telegram_app.configured():
        status_emoji = "🟢" if batch else "🔵"
        lines = [
            f"{status_emoji} PYRESEC Remediation Run — {run_ts[:10]}",
            f"Qualified remediation leads: {len(batch)} | Sent/queued: {contacted}",
            f"Skipped: {skipped_total} (seen {skipped_counts['seen']}, user {skipped_counts['user']}, ICP {skipped_counts['icp']}, no contact {skipped_counts['no_contact']}, clean {skipped_counts['clean']})",
            f"ICP floor: {REMEDIATION_ICP_MIN_SCORE} | Searches run: {searches}",
        ]
        if batch and not dry_run:
            lines.append("A remediation batch was queued in Telegram for approval.")
        elif not batch:
            lines.append("No new qualified remediation leads matched today's searches.")
        try:
            telegram_app.notify("\n".join(lines))
        except Exception as e:
            print(f"  [TELEGRAM NOTIFY ERROR] {e}")

    print()
    print("=" * 60)
    print(f"  Complete. Qualified: {len(batch)} | Sent/queued: {contacted} | Skipped: {skipped_total}")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PYRESEC Remediation Scraper")
    parser.add_argument("--dry-run", action="store_true", help="Preview without sending/queueing")
    parser.add_argument("--max-repos", type=int, default=20, help="Max repos to contact per run")
    args = parser.parse_args()

    if not RESEND_API_KEY and not args.dry_run:
        print("WARNING: RESEND_API_KEY not set. Emails will not be sent.")
        print()

    run_remediation_scraper(dry_run=args.dry_run, max_repos=args.max_repos)
