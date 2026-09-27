#!/usr/bin/env python3
"""
PYRESEC Social Scanner — Autonomous Lead Discovery on X & Farcaster

Daemon that monitors social platforms for developers deploying Web3 or
FastAPI projects, auto-scans their public code, and generates structured
reply drafts for outbound engagement.

Usage:
    python scripts/social_scanner.py                  # Run daemon (poll loop)
    python scripts/social_scanner.py --once           # Single poll cycle
    python scripts/social_scanner.py --dry-run        # Preview without posting
    python scripts/social_scanner.py --platform x     # X only
    python scripts/social_scanner.py --platform farcaster  # Farcaster only

Environment Variables:
    PYRESEC_URL             — PYRESEC API base URL
    PROMO_WALLET_KEY          — Wallet key that pays for sponsored promo scans (old wallet)
    TWITTER_BEARER_TOKEN    — X API v2 bearer token
    NEYNAR_API_KEY          — Neynar API key (Farcaster) — get at neynar.com
    WARPCAST_API_KEY        — Fallback alias for NEYNAR_API_KEY
    SCAN_PROMO_BUDGET       — Max sponsored scans per day (default: 10)
    POLL_INTERVAL           — Seconds between poll cycles (default: 300)
"""

import os
import sys
import json
import time
import argparse
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

# Windows console: allow emoji/unicode in posts (CMD defaults to cp1252)
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import httpx

# ==================== CONFIGURATION ====================

PYRESEC_URL = os.getenv(
    "PYRESEC_URL",
    "https://pyresec-agent-519576377065.us-central1.run.app"
)
PYRESEC_WALLET_KEY = os.getenv("PROMO_WALLET_KEY", "")
DEV_WALLET_ADDRESS = os.getenv("DEV_WALLET_ADDRESS", "")
TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN", "")
NEYNAR_API_KEY = os.getenv("NEYNAR_API_KEY", "") or os.getenv("WARPCAST_API_KEY", "")

SCAN_PROMO_BUDGET = int(os.getenv("SCAN_PROMO_BUDGET", "10"))
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "300"))

# Keyword targets — posts/casts containing these trigger a scan
KEYWORDS = [
    "deployed my smart contract",
    "just deployed to base",
    "just deployed to ethereum",
    "my fastapi app",
    "built a fastapi",
    "new smart contract",
    "contract audit",
    "code review please",
    "security check",
    "foundry project",
    "hardhat project",
    "solidity contract",
    "base mainnet",
    "base sepolia",
    "pushed my code",
    "github.com",
]

# GitHub URL pattern — extract repos to scan
GITHUB_URL_PATTERN = re.compile(
    r"https?://github\.com/([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)"
)

# State file — tracks seen posts to avoid duplicates
STATE_FILE = "scripts/.social_scanner_state.json"

# Daily promo scan counter
DAILY_SCANS_FILE = "scripts/.social_scans_today.json"

# Single-instance lock — prevents two daemons from double-posting
DAEMON_LOCK_FILE = "scripts/.social_scanner.lock"
_daemon_lock_handle = None


def acquire_daemon_lock():
    """Hold an OS-level lock for the daemon's lifetime; exits if already held.

    The lock is released automatically by Windows when the process dies,
    so there is no stale-lock problem.
    """
    global _daemon_lock_handle
    handle = open(DAEMON_LOCK_FILE, "a+")
    try:
        import msvcrt
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write("0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except ImportError:
        pass  # non-Windows: skip locking
    except OSError:
        print("Another social_scanner daemon is already running.")
        print(f"(lock held on {DAEMON_LOCK_FILE}) — refusing to start a second one.")
        sys.exit(1)
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    _daemon_lock_handle = handle  # keep open for process lifetime


# ==================== PLATFORM: X (TWITTER) ====================

def search_x_posts(query: str, max_results: int = 10) -> list[dict]:
    """
    Search recent X posts using Twitter API v2.
    Requires: TWITTER_BEARER_TOKEN (Academic Research or Basic tier)
    """
    if not TWITTER_BEARER_TOKEN:
        return []

    url = "https://api.twitter.com/2/tweets/search/recent"
    headers = {"Authorization": f"Bearer {TWITTER_BEARER_TOKEN}"}
    params = {
        "query": f"{query} -is:retweet lang:en",
        "max_results": max(max_results, 10),
        "tweet.fields": "created_at,author_id,text,public_metrics",
        "expansions": "author_id",
        "user.fields": "name,username,public_metrics",
    }

    with httpx.Client(timeout=30.0) as client:
        try:
            resp = client.get(url, headers=headers, params=params)
            if resp.status_code == 200:
                data = resp.json()
                results = []
                includes = data.get("includes", {})
                users = {u["id"]: u for u in includes.get("users", [])}

                for tweet in data.get("data", []):
                    author = users.get(tweet.get("author_id"), {})
                    results.append({
                        "platform": "x",
                        "id": tweet["id"],
                        "text": tweet["text"],
                        "author_name": author.get("name", ""),
                        "author_username": author.get("username", ""),
                        "author_followers": author.get("public_metrics", {}).get("followers_count", 0),
                        "created_at": tweet.get("created_at", ""),
                        "url": f"https://x.com/{author.get('username', '_')}/status/{tweet['id']}",
                    })
                return results
            elif resp.status_code == 429:
                print(f"  [X RATE LIMITED] Waiting 60s...")
                time.sleep(60)
                return []
            else:
                print(f"  [X ERROR] {resp.status_code}: {resp.text[:200]}")
                return []
        except Exception as e:
            print(f"  [X ERROR] {e}")
            return []


# ==================== PLATFORM: FARCASTER ====================

def search_farcaster_casts(query: str, limit: int = 10) -> list[dict]:
    """
    Search recent Farcaster casts via Neynar API.
    Requires: NEYNAR_API_KEY (get free key at neynar.com)
    """
    if not NEYNAR_API_KEY:
        return []

    url = "https://api.neynar.com/v2/farcaster/cast/search/"
    headers = {"x-api-key": NEYNAR_API_KEY}
    params = {"q": query, "limit": limit}

    with httpx.Client(timeout=30.0) as client:
        try:
            resp = client.get(url, headers=headers, params=params)
            if resp.status_code == 200:
                data = resp.json()
                results = []
                for cast in data.get("result", {}).get("casts", []):
                    author = cast.get("author", {})
                    cast_hash = cast.get("hash", "")
                    username = author.get("username", "")
                    results.append({
                        "platform": "farcaster",
                        "id": cast_hash,
                        "cast_hash": cast_hash,
                        "author_fid": author.get("fid"),
                        "text": cast.get("text", ""),
                        "author_name": author.get("display_name", ""),
                        "author_username": username,
                        "author_followers": author.get("follower_count", 0),
                        "created_at": cast.get("timestamp", ""),
                        "url": f"https://farcaster.xyz/{username}/{cast_hash[:10]}",
                    })
                return results
            elif resp.status_code == 429:
                print(f"  [NEYNAR RATE LIMITED] Waiting 60s...")
                time.sleep(60)
                return []
            else:
                print(f"  [NEYNAR ERROR] {resp.status_code}: {resp.text[:200]}")
                return []
        except Exception as e:
            print(f"  [NEYNAR ERROR] {e}")
            return []


# ==================== GITHUB EXTRACTION ====================

def extract_github_urls(text: str) -> list[str]:
    """Extract GitHub repository URLs from post text."""
    return list(set(GITHUB_URL_PATTERN.findall(text)))


def fetch_github_file(repo: str, filepath: str) -> Optional[str]:
    """Fetch a file from a public GitHub repo."""
    url = f"https://raw.githubusercontent.com/{repo}/main/{filepath}"
    with httpx.Client(timeout=15.0) as client:
        try:
            resp = client.get(url)
            if resp.status_code == 200:
                return resp.text
            # Try master branch
            url = url.replace("/main/", "/master/")
            resp = client.get(url)
            if resp.status_code == 200:
                return resp.text
        except Exception:
            pass
    return None


def fetch_repo_main_file(repo: str) -> Optional[str]:
    """Try to fetch the main source file from a repo."""
    candidates = [
        "main.py", "app.py", "index.js", "index.ts",
        "src/main.py", "src/app.py", "src/index.js",
        "contracts/", "src/contracts/",
    ]

    # Try common entry points
    for filepath in candidates:
        if filepath.endswith("/"):
            # It's a directory — try to list it
            continue
        content = fetch_github_file(repo, filepath)
        if content and len(content.strip()) > 50:
            return content

    return None


# ==================== PYRESEC QUICK SCAN ====================

_x402_client = None


def _get_x402_client():
    """Build an x402 client that auto-handles 402-payments (Base USDC)."""
    global _x402_client
    if _x402_client is not None:
        return _x402_client

    from eth_account import Account
    Account.enable_unaudited_hdwallet_features()
    from x402 import x402ClientConfig, SchemeRegistration, x402Client
    from x402.mechanisms.evm.exact.v1.client import ExactEvmSchemeV1
    from x402.mechanisms.evm.signers import EthAccountSigner

    key = PYRESEC_WALLET_KEY
    if not key.startswith("0x"):
        key = "0x" + key
    account = Account.from_key(key)

    if DEV_WALLET_ADDRESS and account.address.lower() == DEV_WALLET_ADDRESS.lower():
        raise RuntimeError(
            f"PROMO_WALLET_KEY is the dev wallet ({account.address}), which is also "
            f"payTo — the facilitator rejects self-sends. Use the old promo wallet key."
        )

    config = x402ClientConfig(
        schemes=[
            SchemeRegistration(
                network="base",  # Base mainnet (legacy x402 string)
                client=ExactEvmSchemeV1(signer=EthAccountSigner(account)),
                x402_version=1,  # server speaks x402 v1
            ),
        ]
    )
    _x402_client = x402Client.from_config(config)
    return _x402_client


def sponsored_quick_scan(code: str) -> Optional[dict]:
    """
    Call PYRESEC quick-scan using the dev wallet for sponsored promo scans.
    Returns scan results or None if scan fails.
    """
    if not PYRESEC_WALLET_KEY:
        print("    [SCAN] PROMO_WALLET_KEY not set — cannot run sponsored scan")
        return None

    # Check daily budget
    if not check_promo_budget():
        print("    [SCAN] Daily promo budget exhausted")
        return None

    try:
        import asyncio
        from x402.http.clients.httpx import x402HttpxClient

        async def _scan():
            async with x402HttpxClient(_get_x402_client(), timeout=60.0) as client:
                return await client.post(
                    f"{PYRESEC_URL}/v1/audit/quick-scan",
                    json={"code": code[:6000]},
                )

        response = asyncio.run(_scan())

        if response.status_code == 200:
            result = response.json()
            record_promo_scan()
            return result
        else:
            print(f"    [SCAN] PYRESEC returned {response.status_code}: {response.text[:150]}")
            return None
    except ImportError as e:
        print(f"    [SCAN] Missing dependency: {e}. Run: pip install \"x402[evm]\"")
        return None
    except Exception as e:
        print(f"    [SCAN] Error: {e}")
        return None


# ==================== DAILY BUDGET TRACKING ====================

def load_daily_scans() -> dict:
    if os.path.exists(DAILY_SCANS_FILE):
        with open(DAILY_SCANS_FILE, "r") as f:
            return json.load(f)
    return {"date": "", "count": 0}


def save_daily_scans(data: dict):
    with open(DAILY_SCANS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def check_promo_budget() -> bool:
    data = load_daily_scans()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if data.get("date") != today:
        return True
    return data.get("count", 0) < SCAN_PROMO_BUDGET


def record_promo_scan():
    data = load_daily_scans()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if data.get("date") != today:
        data = {"date": today, "count": 0}
    data["count"] = data.get("count", 0) + 1
    save_daily_scans(data)


# ==================== REPLY GENERATOR ====================

def generate_reply(post: dict, scan_result: Optional[dict], github_repo: Optional[str]) -> str:
    """
    Generate a structured Markdown reply draft.
    Returns the reply text ready to be posted.
    """
    author = post.get("author_username", "dev")
    platform = post.get("platform", "social")

    if scan_result:
        findings = scan_result.get("sast_findings", [])
        num_findings = len(findings)
        file_hash = scan_result.get("file_hash", "")[:8]

        severity_counts = {}
        for f in findings:
            sev = f.get("severity", "UNKNOWN")
            severity_counts[sev] = severity_counts.get(sev, 0) + 1

        severity_str = ", ".join(f"{v} {k}" for k, v in severity_counts.items()) if severity_counts else "Clean"

        reply = f"""Hey @{author}, saw your post — ran a quick security scan on your code.

**PYRESEC Quick Scan Results:**
- Findings: {num_findings} ({severity_str})
- File hash: `{file_hash}`
- Scan tier: $0.01 USDC (sponsored)

"""
        if findings:
            reply += "**Top findings:**\n"
            for i, f in enumerate(findings[:3], 1):
                reply += f"{i}. **[{f.get('severity', '?')}]** {f.get('type', 'Unknown')} — {f.get('cwe', 'N/A')} (line {f.get('line_number', '?')})\n"

            reply += f"\nGet the full audit + auto-patch for $5.00:\n"
        else:
            reply += "Code looks clean. Want a deeper audit ($0.50) or auto-patch ($5.00)?\n"

        if github_repo:
            reply += f"\n{PYRESEC_URL}/docs"
        else:
            reply += f"\n{PYRESEC_URL}/docs"

    else:
        # No scan result — generic engagement
        reply = f"""Hey @{author}, looks like you're building something cool!

If you want a quick security check on your code, PYRESEC does SAST/SCA scans via x402 micropayments — no account needed.

$0.01 for a quick scan | $0.50 for full audit | $5.00 for auto-patch

{PYRESEC_URL}/docs"""

    return reply


# ==================== STATE MANAGEMENT ====================

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    return {"seen_ids": [], "last_poll": {}}


def save_state(state: dict):
    # Keep only last 1000 seen IDs to prevent bloat
    state["seen_ids"] = state.get("seen_ids", [])[-1000:]
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def is_seen(post_id: str, state: dict) -> bool:
    return post_id in state.get("seen_ids", [])


def mark_seen(post_id: str, state: dict):
    if "seen_ids" not in state:
        state["seen_ids"] = []
    state["seen_ids"].append(post_id)


# ==================== APPROVAL QUEUE ====================

QUEUE_FILE = "scripts/.reply_queue.json"

# Signals that a post comes from an actual builder (not news/commentary)
BUILDER_SIGNALS = [
    "i built", "i just built", "built a", "built my", "just deployed",
    "deployed my", "deployed a", "my app", "my project", "my contract",
    "pushed my", "just pushed", "just launched", "i launched", "i made",
    "i wrote", "my repo", "github.com", "open source", "my fastapi",
    "finished building", "shipped", "live on base", "now live",
]

MAX_LEADS_PER_CYCLE = int(os.getenv("MAX_LEADS_PER_CYCLE", "5"))


def load_queue() -> list[dict]:
    if os.path.exists(QUEUE_FILE):
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_queue(queue: list[dict]):
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(queue[-500:], f, indent=2, ensure_ascii=False)


def is_builder_lead(post: dict) -> bool:
    if post.get("cast_hash") and extract_github_urls(post.get("text", "")):
        return True
    text = (post.get("text") or "").lower()
    return any(sig in text for sig in BUILDER_SIGNALS)


# ==================== TELEGRAM APPROVAL FLOW ====================

def send_leads_to_telegram(replies: list[dict], verbose: bool = True) -> int:
    """
    Queue Farcaster leads and send them to Telegram with Approve/Reject buttons.
    Returns number of leads sent.
    """
    import telegram_app

    queue = load_queue()
    sent = 0
    for r in replies:
        if sent >= MAX_LEADS_PER_CYCLE:
            break
        if r["platform"] != "farcaster":
            continue
        if not is_builder_lead(r["post"]):
            continue

        qid = f"{int(time.time() * 1000)}-{r['post']['id'][:8]}"
        header = (
            f"🔔 Lead {sent + 1}/{MAX_LEADS_PER_CYCLE} — Farcaster\n"
            f"@{r['post']['author_username']} ({r['post'].get('author_followers', 0)} followers)\n"
            f"Post: {r['post'].get('url', '')}\n"
            f"Scanned: {'yes' if r['scanned'] else 'no'}"
        )
        try:
            msg_id = telegram_app.send_lead(header, r["reply"], qid)
        except Exception as e:
            if verbose:
                print(f"  [TG ERROR] {e}")
            continue

        queue.append({
            "qid": qid,
            "platform": "farcaster",
            "status": "pending",
            "tg_message_id": msg_id,
            "reply": r["reply"],
            "cast_hash": r["post"].get("cast_hash", ""),
            "author_fid": r["post"].get("author_fid"),
            "author_username": r["post"].get("author_username", ""),
            "post_url": r["post"].get("url", ""),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        sent += 1
        if verbose:
            print(f"  [TG] Sent lead @{r['post']['author_username']} for approval")

    save_queue(queue)
    return sent


def handle_telegram_updates(updates: list[dict], verbose: bool = True) -> int:
    """Process Approve/Reject callbacks. Returns number of approved posts."""
    import telegram_app
    import farcaster_api

    queue = load_queue()
    handled = 0
    my_chat = telegram_app.chat_id()

    for upd in updates:
        cb = upd.get("callback_query")
        if not cb:
            continue
        cb_id = cb.get("id", "")
        data = cb.get("data", "")
        from_id = str((cb.get("from") or {}).get("id", ""))

        # Only accept buttons from the owner's private chat
        if from_id != my_chat:
            telegram_app.answer_callback(cb_id, "Unauthorized")
            continue
        if not data.startswith(("ap:", "rj:")):
            telegram_app.answer_callback(cb_id)
            continue

        action, qid = data.split(":", 1)
        entry = next((q for q in queue if q["qid"] == qid), None)
        if not entry:
            telegram_app.answer_callback(cb_id, "Queue entry not found")
            continue
        if entry["status"] != "pending":
            telegram_app.answer_callback(cb_id, f"Already {entry['status']}")
            continue

        tg_msg = entry.get("tg_message_id")

        if action == "rj":
            entry["status"] = "rejected"
            telegram_app.answer_callback(cb_id, "Rejected")
            if tg_msg:
                telegram_app.edit_message(
                    tg_msg,
                    f"❌ Rejected — @{entry['author_username']}\n{entry['post_url']}",
                )
            if verbose:
                print(f"  [TG] Rejected @{entry['author_username']}")
            handled += 1
            continue

        # === APPROVE → publish to Farcaster ===
        telegram_app.answer_callback(cb_id, "Posting...")
        try:
            text = farcaster_api.truncate_to_bytes(entry["reply"])
            result = farcaster_api.publish_cast(
                text,
                parent_hash=entry.get("cast_hash") or None,
                parent_fid=entry.get("author_fid"),
            )
            entry["status"] = "posted"
            entry["cast_url"] = result.get("url", "")
            if tg_msg:
                telegram_app.edit_message(
                    tg_msg,
                    f"✅ Posted to Farcaster — @{entry['author_username']}\n"
                    f"{result.get('url', '')}",
                )
            if verbose:
                print(f"  [TG] Posted reply → {result.get('url', '')}")
        except Exception as e:
            entry["status"] = "error"
            entry["error"] = str(e)
            if tg_msg:
                telegram_app.edit_message(
                    tg_msg,
                    f"⚠️ Post failed — @{entry['author_username']}\n{e}",
                )
            if verbose:
                print(f"  [TG ERROR] publish failed: {e}")
        handled += 1

    save_queue(queue)
    return handled


# ==================== MAIN POLL LOOP ====================

def poll_once(platforms: list[str], dry_run: bool = False, verbose: bool = True) -> list[dict]:
    """
    Single poll cycle across all platforms.
    Returns list of generated replies.
    """
    state = load_state()
    replies = []

    if verbose:
        print(f"  Platforms: {', '.join(platforms)}")
        print(f"  X key: {'SET' if TWITTER_BEARER_TOKEN else 'MISSING'}")
        print(f"  Neynar key: {'SET' if NEYNAR_API_KEY else 'MISSING'}")
        print(f"  Keywords: {len(KEYWORDS)}")

    for keyword in KEYWORDS:
        # === X (Twitter) ===
        if "x" in platforms:
            posts = search_x_posts(keyword, max_results=5)
            for post in posts:
                if is_seen(post["id"], state):
                    continue

                if verbose:
                    print(f"\n[X] @{post['author_username']}: {post['text'][:80]}...")

                # Extract GitHub URLs
                github_urls = extract_github_urls(post["text"])
                github_repo = github_urls[0] if github_urls else None
                scan_result = None

                # If we found a GitHub repo, try to scan it
                if github_repo:
                    if verbose:
                        print(f"  Found repo: {github_repo}")
                    code = fetch_repo_main_file(github_repo)
                    if code:
                        if verbose:
                            print(f"  Scanning {len(code)} chars of code...")
                        scan_result = sponsored_quick_scan(code)

                # Generate reply
                reply = generate_reply(post, scan_result, github_repo)
                replies.append({
                    "platform": "x",
                    "post": post,
                    "reply": reply,
                    "scanned": scan_result is not None,
                })

                if verbose:
                    print(f"  Reply draft:\n{reply[:200]}...")

                mark_seen(post["id"], state)

            time.sleep(2)  # Rate limit between platforms

        # === Farcaster ===
        if "farcaster" in platforms:
            casts = search_farcaster_casts(keyword, limit=5)
            for cast in casts:
                if is_seen(cast["id"], state):
                    continue

                if verbose:
                    print(f"\n[FARCASTER] @{cast['author_username']}: {cast['text'][:80]}...")

                github_urls = extract_github_urls(cast["text"])
                github_repo = github_urls[0] if github_urls else None
                scan_result = None

                if github_repo:
                    if verbose:
                        print(f"  Found repo: {github_repo}")
                    code = fetch_repo_main_file(github_repo)
                    if code:
                        if verbose:
                            print(f"  Scanning {len(code)} chars of code...")
                        scan_result = sponsored_quick_scan(code)

                reply = generate_reply(cast, scan_result, github_repo)
                replies.append({
                    "platform": "farcaster",
                    "post": cast,
                    "reply": reply,
                    "scanned": scan_result is not None,
                })

                if verbose:
                    print(f"  Reply draft:\n{reply[:200]}...")

                mark_seen(cast["id"], state)

            time.sleep(2)

    save_state(state)
    return replies


def run_daemon(platforms: list[str], dry_run: bool = False):
    """Continuous poll loop: social discovery + Telegram approval queue."""
    import telegram_app

    tg_enabled = telegram_app.configured() and not dry_run

    print("=" * 60)
    print("  PYRESEC Social Scanner — Autonomous Lead Discovery")
    print("=" * 60)
    print(f"  Platforms: {', '.join(platforms)}")
    print(f"  Poll interval: {POLL_INTERVAL}s")
    print(f"  Promo budget: {SCAN_PROMO_BUDGET}/day")
    print(f"  Dry run: {dry_run}")
    print(f"  Telegram approvals: {'ON' if tg_enabled else 'OFF (dry-run or no token)'}")
    print(f"  Keywords: {len(KEYWORDS)}")
    print("=" * 60)

    if not TWITTER_BEARER_TOKEN and "x" in platforms:
        print("\n[WARNING] TWITTER_BEARER_TOKEN not set — X scanning disabled")
    if not NEYNAR_API_KEY and "farcaster" in platforms:
        print("\n[WARNING] NEYNAR_API_KEY not set — Farcaster scanning disabled (get free key at neynar.com)")
    if tg_enabled:
        try:
            telegram_app.notify("🤖 PYRESEC lead engine started. New leads will arrive here.")
        except Exception as e:
            print(f"\n[WARNING] Telegram init failed: {e}")
            tg_enabled = False

    offset = 0
    next_social = 0.0

    while True:
        try:
            # --- Telegram approvals first (picks up taps within 25s) ---
            if tg_enabled:
                updates = telegram_app.get_updates(offset, timeout=25)
                for upd in updates:
                    offset = upd["update_id"] + 1
                if updates:
                    handle_telegram_updates(updates)

            # --- Social poll (every POLL_INTERVAL) ---
            now = time.time()
            if now >= next_social:
                print(f"\n[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] Polling...")
                replies = poll_once(platforms, dry_run=dry_run)

                if replies:
                    print(f"\n  Generated {len(replies)} reply drafts")
                    for r in replies:
                        print(f"    [{r['platform']}] @{r['post']['author_username']} — scanned: {r['scanned']}")
                    if tg_enabled:
                        sent = send_leads_to_telegram(replies)
                        print(f"  Sent {sent} lead(s) to Telegram for approval")
                else:
                    print("  No new leads found")

                next_social = now + POLL_INTERVAL

            if not tg_enabled:
                time.sleep(30)

        except KeyboardInterrupt:
            print("\n[SHUTDOWN] Stopping scanner...")
            break
        except Exception as e:
            print(f"\n[ERROR] {e}")
            time.sleep(10)


# ==================== ENTRY POINT ====================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PYRESEC Social Scanner")
    parser.add_argument("--once", action="store_true", help="Single poll cycle then exit")
    parser.add_argument("--process-approvals", action="store_true",
                        help="Process pending Telegram approvals once then exit")
    parser.add_argument("--dry-run", action="store_true", help="Preview mode — no scans posted")
    parser.add_argument("--platform", choices=["x", "farcaster", "all"], default="all",
                        help="Platform to scan (default: all)")
    parser.add_argument("--verbose", action="store_true", default=True, help="Verbose output")
    args = parser.parse_args()

    platform_map = {
        "x": ["x"],
        "farcaster": ["farcaster"],
        "all": ["x", "farcaster"],
    }
    platforms = platform_map[args.platform]

    if args.process_approvals:
        import telegram_app
        offset = 0
        updates = telegram_app.get_updates(offset, timeout=10)
        if updates:
            handled = handle_telegram_updates(updates)
            print(f"Processed {len(updates)} update(s), {handled} action(s).")
        else:
            print("No pending approvals.")
        sys.exit(0)

    if args.once:
        replies = poll_once(platforms, dry_run=args.dry_run, verbose=args.verbose)
        print(f"\n{'='*60}")
        print(f"  Scan complete. {len(replies)} replies generated.")
        print(f"{'='*60}")

        import telegram_app
        if telegram_app.configured() and not args.dry_run:
            sent = send_leads_to_telegram(replies, verbose=args.verbose)
            print(f"  {sent} lead(s) sent to Telegram for approval.")
            print("  Start the daemon to receive approvals:")
            print("    python scripts\\social_scanner.py --platform farcaster")
        else:
            for i, r in enumerate(replies, 1):
                print(f"\n--- Reply {i} [{r['platform']}] ---")
                print(r["reply"])
    else:
        acquire_daemon_lock()
        run_daemon(platforms, dry_run=args.dry_run)
