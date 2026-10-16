#!/usr/bin/env python3
"""PYRESEC Shadow Audit engine — weekly anonymized content from public repos.

Scans recent popular repos, keeps only CRITICAL/HIGH results, and produces
an anonymized case study (markdown) plus ready-to-post social copy.

Usage:
    python scripts/shadow_audit.py                # next candidates (limit 1)
    python scripts/shadow_audit.py --limit 3
    python scripts/shadow_audit.py --list         # show state

Outputs: reports/shadow_audit/case_study_<repo>_<date>.md (+ .social.json)
State:   scripts/.shadow_audit_state.json
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import content_engine
import probe
import playbooks

STATE_FILE = ROOT / "scripts" / ".shadow_audit_state.json"
OUT_DIR = ROOT / "reports" / "shadow_audit"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Fallback pool if no lead-engine history exists (popular org repos).
FALLBACK_CANDIDATES = [
    "uniswap/v3-core",
    "Uniswap/universal-router",
    "aave/aave-v3-core",
    "lidofinance/lido-dao",
    "OpenZeppelin/openzeppelin-contracts",
    "safe-global/safe-smart-account",
    "foundry-rs/forge-std",
    "ethereum/solidity",
    "solana-labs/solana-program-library",
    "cosmos/cosmos-sdk",
    "ethereum/go-ethereum",
    "fastapi/fastapi",
    "tiangolo/sqlmodel",
    "encode/starlette",
    "django/django",
    "pallets/flask",
    "expressjs/express",
    "nestjs/nest",
    "prisma/prisma",
    "vercel/next.js",
]


def load_candidates() -> list[str]:
    """Lead-engine repos first (already qualified), then seen history."""
    ordered: list[str] = []
    try:
        queue = json.loads((ROOT / "scripts" / ".reply_queue.json").read_text(encoding="utf-8"))
        for item in queue if isinstance(queue, list) else []:
            repo = item.get("repo")
            if repo:
                ordered.append(repo)
    except (OSError, json.JSONDecodeError):
        pass
    try:
        seen = json.loads((ROOT / "scripts" / ".seen_repos.json").read_text(encoding="utf-8"))
        ordered.extend(seen.get("repos", []))
    except (OSError, json.JSONDecodeError):
        pass
    if not ordered:
        ordered = list(FALLBACK_CANDIDATES)
    return ordered


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"done": {}, "generated": []}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False),
                          encoding="utf-8")


def run(limit: int = 1) -> list[str]:
    state = load_state()
    done = state.get("done", {})
    produced = []

    for repo in load_candidates():
        if len(produced) >= limit:
            break
        if repo in done:
            continue

        print(f"[shadow] scanning {repo} ...")
        try:
            code = probe.fetch_repo_main_file(repo)
            if not code:
                done[repo] = "no_code"
                continue
            scan = probe.local_scan(code)
            rating = playbooks.risk_rating(scan)
        except Exception as exc:  # keep the batch alive on a single failure
            print(f"[shadow]   error: {exc}")
            done[repo] = "error"
            continue

        print(f"[shadow]   rating: {rating}")
        if rating not in ("CRITICAL", "HIGH"):
            done[repo] = f"rated_{rating}"
            continue

        findings = scan.get("findings", [])
        md = content_engine.build_case_study(repo, code, scan, anonymize=True)
        social = content_engine._build_social_copy(repo, findings, anonymize=True)

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        slug = repo.replace("/", "_").lower()
        md_path = OUT_DIR / f"case_study_{slug}_{stamp}.md"
        json_path = OUT_DIR / f"case_study_{slug}_{stamp}.social.json"
        md_path.write_text(md, encoding="utf-8")
        json_path.write_text(json.dumps(social, indent=2, ensure_ascii=False),
                             encoding="utf-8")

        done[repo] = f"published_{stamp}"
        state.get("generated", []).append({
            "repo": repo, "rating": rating, "date": stamp,
            "findings": len(findings), "md": str(md_path.name),
        })
        produced.append(repo)
        print(f"[shadow]   -> {md_path.name}")

    save_state(state)
    print(f"\n[shadow] generated {len(produced)} case study(ies)")
    for r in produced:
        print(f"  - {r}")
    return produced


def main() -> None:
    parser = argparse.ArgumentParser(description="PYRESEC Shadow Audit content engine")
    parser.add_argument("--limit", type=int, default=1, help="case studies per run")
    parser.add_argument("--list", action="store_true", help="show state and exit")
    args = parser.parse_args()

    if args.list:
        state = load_state()
        print(json.dumps(state, indent=2, ensure_ascii=False))
        return

    run(limit=args.limit)


if __name__ == "__main__":
    main()
