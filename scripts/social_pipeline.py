#!/usr/bin/env python3
"""PYRESEC Social Pipeline — case studies -> channel-ready Zero-Day posts.

Implements the Month 1 "Zero-Day Breakdown" blueprint for each shadow-audit
case study:

  Hook      the flaw pattern (CWE) + severity, no corporate fluff
  Content   step-by-step code-level breakdown of how the flaw works
  CTA       real engine stats + free-baseline link

Channels:
  X         thread (each tweet <= 280 chars)  — manual post (copy from draft)
  Farcaster single cast <= 1024 bytes, /security channel — CAN auto-post
  LinkedIn  longer narrative                  — manual post

Usage:
  python scripts/social_pipeline.py                 # draft + send Telegram approval card
  python scripts/social_pipeline.py --print-only    # preview locally, nothing queued
  python scripts/social_pipeline.py --post-farcaster  # bypass gate, publish now (testing)
  python scripts/social_pipeline.py --case <slug>   # pick a specific case study

Approval: the card lands in the same Telegram flow as lead approvals.
On Approve (daemon running): Farcaster cast auto-posts to /security;
X thread + LinkedIn texts arrive as messages for copy-paste (their APIs
need business apps — manual posting for now, automatable later).

Drafts: reports/shadow_audit/posts_<slug>_<date>.md (+ .posts.json)
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
try:  # Windows console (cp1252) can't print emoji — drafts use UTF-8 files
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

CASE_DIR = ROOT / "reports" / "shadow_audit"
OUTREACH_RUNS = ROOT / "scripts" / ".outreach_runs.json"

SERVICES_URL = (os.getenv("PYRESEC_URL",
                          "https://pyresec-agent-519576377065.us-central1.run.app")
                + "/services")

# CWE knowledge — how the flaw actually works (the "Content" section).
CWE_NOTES = {
    "CWE-1395": (
        "dependency on a vulnerable third-party component",
        "the app ships a pinned dependency with a known CVE — the flaw isn't "
        "in your code, it's in the code you inherit. Attackers scan lockfiles "
        "on public repos and hit the endpoint before you patch",
        "`pip-audit` / `npm audit` against your lockfile",
    ),
    "CWE-89": (
        "SQL injection",
        "user input concatenated into a query string instead of parameterized",
        "search for f-strings/`+` building SELECT/INSERT — use bound params",
    ),
    "CWE-798": (
        "hard-coded credentials",
        "API keys / passwords committed in source — git history keeps them "
        "forever even after deletion",
        "rotate the key FIRST, then scrub history + move to a secret manager",
    ),
    "CWE-78": (
        "OS command injection",
        "shelling out with unsanitized input (subprocess/os.system)",
        "never pass request data to a shell; allowlist arguments",
    ),
    "CWE-22": (
        "path traversal",
        "file paths built from user input allow ../ escapes to read anything "
        "the process can reach",
        "resolve against a fixed root and reject paths that escape it",
    ),
    "CWE-502": (
        "insecure deserialization",
        "pickle/yaml.load on untrusted bytes can execute arbitrary code on parse",
        "use json or safe loaders; never unpickle network data",
    ),
    "CWE-79": (
        "cross-site scripting (XSS)",
        "unescaped user content rendered into the DOM — session theft and "
        "credential capture",
        "context-aware escaping/templating on every sink",
    ),
    "CWE-862": (
        "missing authorization",
        "endpoints check that you're logged in, not that you're ALLOWED — "
        "any authenticated user can reach other tenants' data",
        "authorize per-object against the caller's identity",
    ),
}

FALLBACK_NOTE = (
    "a scanner-confirmed weakness in the production codepath",
    "flagged with line-level evidence by static analysis — the exploitable "
    "condition ships with the next deploy unless it's patched and documented",
    "diff-aware re-scan on every merge",
)


def latest_case(case_arg: str = "") -> dict | None:
    """Locate the newest case study pair (md + social json)."""
    mds = sorted(CASE_DIR.glob("case_study_*.md"))
    if case_arg:
        mds = [m for m in mds if case_arg.lower() in m.name.lower()] or mds
    if not mds:
        return None
    md_path = mds[-1]
    social_path = md_path.with_suffix("").with_suffix(".social.json")
    if not social_path.exists():
        social_path = Path(str(md_path)[: -len(".md")] + ".social.json")
    social = {}
    if social_path.exists():
        try:
            social = json.loads(social_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"md_path": md_path, "md": md_path.read_text(encoding="utf-8"),
            "social": social, "slug": md_path.stem.replace("case_study_", "")}


def parse_case(md: str) -> dict:
    """Pull rating + finding blocks out of the case-study markdown."""
    m = re.search(r"\*\*Risk rating:\*\* (\w+)", md)
    rating = m.group(1) if m else "UNKNOWN"
    findings = []
    for fm in re.finditer(
            r"\*\*\[\d+\] \[(\w+)\] ([\w_]+) (\S+?)\*\* \(([^)]*)\)\n> ?(.*)",
            md):
        findings.append({
            "severity": fm.group(1), "type": fm.group(2), "cwe": fm.group(3),
            "loc": fm.group(4), "description": fm.group(5).strip(),
        })
    return {"rating": rating, "findings": findings}


def engine_stats() -> dict:
    """Real numbers from the outreach engine for the CTA."""
    try:
        runs = json.loads(OUTREACH_RUNS.read_text(encoding="utf-8"))
        last = runs[-1]
        return {"seen_total": last.get("seen_total", 0),
                "qualified": sum(r.get("qualified", 0) for r in runs[-7:])}
    except (OSError, json.JSONDecodeError, IndexError):
        return {"seen_total": 0, "qualified": 0}


def _cwe_note(cwe: str) -> tuple[str, str, str]:
    for key, note in CWE_NOTES.items():
        if key.lower() in (cwe or "").lower():
            return note
    return FALLBACK_NOTE


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def build_x_thread(case: dict, stats: dict) -> list[str]:
    rating = case["rating"]
    f = case["findings"][0] if case["findings"] else {}
    cwe = f.get("cwe", "")
    what, how, check = _cwe_note(cwe)
    sev = (f.get("severity") or rating).upper()

    t1 = _clip(
        f"We scanned a live production codebase this week with our own engine.\n\n"
        f"Rated {rating}. Top flaw: {sev} — {what} ({cwe}).\n\n"
        f"How it actually works 🧵", 280)

    t2 = _clip(
        f"The mechanism:\n\n{how}.\n\n"
        f"Where to look: {check}.", 280)

    seen = stats.get("seen_total", 0)
    t3 = _clip(
        f"Same engine, {seen:,}+ public repos checked so far — this pattern "
        f"shows up constantly.\n\n"
        f"Free baseline for your repo (proof attached, no account):\n"
        f"{SERVICES_URL}", 280)
    return [t1, t2, t3]


def build_farcaster(case: dict, stats: dict) -> str:
    rating = case["rating"]
    f = case["findings"][0] if case["findings"] else {}
    cwe = f.get("cwe", "")
    what, how, _ = _cwe_note(cwe)
    seen = stats.get("seen_total", 0)
    text = (
        f"PYRESEC scan log: live production repo, {rating} rating.\n\n"
        f"Top flaw — {what} ({cwe}): {how}.\n\n"
        f"{seen:,}+ public repos checked by this engine. Free baseline with "
        f"line-level proof: {SERVICES_URL}"
    )
    return text


def build_linkedin(case: dict, stats: dict) -> str:
    rating = case["rating"]
    f = case["findings"][0] if case["findings"] else {}
    cwe = f.get("cwe", "")
    what, how, check = _cwe_note(cwe)
    seen = stats.get("seen_total", 0)
    qualified = stats.get("qualified", 0)
    return (
        f"Case study: a {rating}-rated production codebase, scanned with the "
        f"same PYRESEC engine that powers our paid engagements.\n\n"
        f"Top finding — {what} ({cwe}).\n\n"
        f"In plain terms: {how}.\n\n"
        f"If you maintain a public repo, the fix discipline is simple: {check}, "
        f"then prove it — re-scan on every merge, not once a quarter.\n\n"
        f"We've sweep-checked {seen:,}+ public repos to date; {qualified} new "
        f"funded-team-grade targets entered our pipeline this week alone. "
        f"Security posture should be a verifiable artifact, not a slide.\n\n"
        f"Free baseline for your repo (evidence attached): {SERVICES_URL}\n\n"
        f"#Web3Security #SmartContracts #AppSec #DevSecOps"
    )


def render_draft(case: dict, stats: dict, slug: str) -> dict:
    thread = build_x_thread(case, stats)
    return {
        "slug": slug,
        "generated": datetime.now(timezone.utc).isoformat(),
        "rating": case["rating"],
        "x_thread": thread,
        "farcaster": build_farcaster(case, stats),
        "linkedin": build_linkedin(case, stats),
    }


def save_draft(draft: dict) -> tuple[Path, Path]:
    md = [
        f"# Social Drafts — {draft['slug']} ({draft['rating']})",
        f"Generated: {draft['generated'][:16]} UTC",
        "",
        "## X / Twitter thread (post top → bottom)",
        "",
    ]
    for i, tweet in enumerate(draft["x_thread"], 1):
        md += [f"### Tweet {i}/{len(draft['x_thread'])} ({len(tweet)} chars)", "",
               tweet, "", "---", ""]
    md += ["## Farcaster cast (auto-postable)", "", draft["farcaster"], "",
           "---", "", "## LinkedIn post", "", draft["linkedin"], ""]
    md_path = CASE_DIR / f"posts_{draft['slug']}.md"
    json_path = CASE_DIR / f"posts_{draft['slug']}.social.json"
    md_path.write_text("\n".join(md), encoding="utf-8")
    json_path.write_text(json.dumps(draft, indent=2, ensure_ascii=False),
                         encoding="utf-8")
    return md_path, json_path


def post_farcaster_thread(text: str, channels: list[str] | None = None) -> list[dict]:
    """Publish cast + 1 reply continuation if over 1024 bytes."""
    import farcaster_api as fa
    chunks = []
    encoded = text.encode("utf-8")
    if len(encoded) <= 1024:
        chunks = [text]
    else:
        cut = text
        while cut.encode("utf-8") > 1024:
            cut = cut[: int(len(cut) * 0.9)]
        rest = text[len(cut):].strip()
        chunks = [cut.rstrip() + "…", rest] if rest else [cut]
    results = []
    parent_hash = parent_fid = None
    state = fa.load_state()
    fid = state.get("fid")
    for chunk in chunks:
        res = fa.publish_cast(fa.truncate_to_bytes(chunk), parent_hash, parent_fid,
                              channels=channels if parent_hash is None else None)
        results.append(res)
        parent_hash, parent_fid = res.get("hash"), fid
    return results


def queue_for_telegram(draft: dict, verbose: bool = True) -> str:
    """Send an approval card to Telegram; entry waits in the shared queue.

    The running social_scanner daemon handles the Approve tap: publishes the
    Farcaster cast and delivers the X thread + LinkedIn texts for copy-paste.
    """
    import time
    import social_scanner
    import telegram_app

    qid = f"{int(time.time() * 1000)}-social"
    tweets = draft.get("x_thread", [])
    preview = (tweets[0] if tweets else draft.get("farcaster", ""))[:600]
    header = (
        f"📱 Social drafts ready — {draft['slug']} ({draft['rating']})\n"
        f"On approve: Farcaster auto-post (/security) + X thread & LinkedIn "
        f"texts delivered here for copy-paste."
    )
    body = f"Preview (X tweet 1):\n{preview}\n\n…plus {max(len(tweets)-1, 0)} more " \
           f"tweet(s) + LinkedIn post."
    msg_id = telegram_app.send_lead(header, body, qid)

    queue = social_scanner.load_queue()
    queue.append({
        "qid": qid,
        "kind": "social_post",
        "status": "pending",
        "tg_message_id": msg_id,
        "draft": draft,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    social_scanner.save_queue(queue)
    if verbose:
        print(f"[social] approval card sent to Telegram (qid={qid})")
    return qid


def main() -> None:
    p = argparse.ArgumentParser(description="PYRESEC Social Pipeline")
    p.add_argument("--case", default="", help="case-study slug substring")
    p.add_argument("--print-only", action="store_true",
                   help="print drafts only — do not queue for Telegram")
    p.add_argument("--post-farcaster", action="store_true",
                   help="bypass the approval gate and publish to Farcaster now")
    p.add_argument("--channel", default="security",
                   help="Farcaster channel id (default: security)")
    args = p.parse_args()

    case_file = latest_case(args.case)
    if not case_file:
        raise SystemExit("no case studies in reports/shadow_audit/ — "
                         "run scripts/shadow_audit.py first")
    case = parse_case(case_file["md"])
    stats = engine_stats()
    draft = render_draft(case, stats, case_file["slug"])
    md_path, _ = save_draft(draft)

    print(f"[social] draft: {md_path}")
    print(f"[social] rating {draft['rating']} | stats: {stats}")
    print("\n--- X thread ---")
    for i, t in enumerate(draft["x_thread"], 1):
        print(f"\n[tweet {i}/{len(draft['x_thread'])} | {len(t)} chars]\n{t}")
    print(f"\n--- Farcaster ({len(draft['farcaster'].encode())} bytes) ---\n"
          f"{draft['farcaster']}")
    print(f"\n--- LinkedIn ---\n{draft['linkedin']}")

    if args.post_farcaster:
        print(f"\n[social] publishing to Farcaster /{args.channel} ...")
        results = post_farcaster_thread(draft["farcaster"], channels=[args.channel])
        for r in results:
            print(f"[social] cast: {r.get('url') or r}")
    elif args.print_only:
        print("\n[social] print-only — nothing queued.")
    else:
        queue_for_telegram(draft)
        print("[social] approve in Telegram (same flow as lead approvals). "
              "Keep the social_scanner daemon running.")


if __name__ == "__main__":
    main()
