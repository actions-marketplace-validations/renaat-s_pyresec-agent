#!/usr/bin/env python3
"""PYRESEC Build-in-Public engine — "Code Drop" post generation.

Generates cold, precise architectural breakdowns of Nanoclone Systems'
own automation pipelines. No emojis, no marketing language. Numbers are
pulled from live engine state where possible.

Usage:
  python scripts/buildinpublic_engine.py                 # queue for approval
  python scripts/buildinpublic_engine.py --print-only    # drafts only
  python scripts/buildinpublic_engine.py --topic ast-parsing
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import social_pipeline  # noqa: E402

REPORT_DIR = ROOT / "reports" / "buildinpublic"


def live_stats() -> dict:
    s = social_pipeline.engine_stats()
    stats = {
        "seen_total": s.get("seen_total", 0),
        "qualified": s.get("qualified", 0),
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }
    try:
        fu = json.loads((ROOT / "scripts" / ".followup_state.json").read_text(encoding="utf-8"))
        stats["followup1"] = sum(1 for v in fu.values() if v.get("fu1"))
        stats["followup2"] = sum(1 for v in fu.values() if v.get("fu2"))
    except Exception:
        stats["followup1"] = stats["followup2"] = 0
    try:
        q = json.loads((ROOT / "scripts" / ".reply_queue.json").read_text(encoding="utf-8"))
        stats["queue_total"] = len(q)
    except Exception:
        stats["queue_total"] = 0
    return stats


TOPICS = [
    {
        "slug": "ast-parsing",
        "title": "AST parsing in the discovery layer",
        "linkedin": """Our security agent reviews {seen_total} public repositories without a single human opening a pull request. The discovery layer is deterministic, not model-driven.

Architecture, condensed: a rotated query surface (~40 seeded GitHub searches, hash-picked daily so the sampling does not stagnate) returns candidate repositories. Each candidate is scored on structural signals — dependency manifests, CI configuration, framework fingerprints, presence of bot-authored dependency commits. Qualification rate: {qualified} in {seen_total}. Roughly 0.2 percent survive. That ratio is the product.

The scan stage runs pattern analysis against the candidate's primary source files: injection surfaces, deserialization sinks, hardcoded credential shapes, unresolved dependency versions with known CVE mappings. Output is not a chat transcript. It is a structured finding set — CWE-mapped, severity-ranked — rendered into a signed PDF artifact and a case-study draft. Evidence before payment is the commercial model; the pipeline is why the unit economics hold.

What most teams charge six figures to staff, we execute as scheduled jobs. The agent does not get tired, does not oversell, and does not report findings it cannot show you in source.

Renaat Sibanda
Founder, NanoClone Systems""",
        "farcaster": """Discovery layer stats, current cycle:

{seen_total} repositories ingested
{qualified} qualified (0.2%)
Deterministic scoring. No model in the qualification path.

Pipeline: rotated GitHub queries -> structural scoring (manifests, CI shape, dependency-bot fingerprints) -> CWE-mapped static analysis on primary source files -> signed PDF artifact.

The scan engine reads code, not marketing briefs. Findings ship with the exact file, line, and mechanism. If it cannot prove it, it does not publish it.

NanoClone Systems. Autonomous security infrastructure.""",
        "x_thread": [
            "Our security agent has reviewed {seen_total} repositories with zero human triage.\n\nQualification rate: {qualified} ({pct:.2f}%).\n\nDeterministic scoring, not vibes. Architecture breakdown below.",
            "Scoring signals: dependency manifests, CI shape, framework fingerprints, bot-authored dependency commits. Survivors get CWE-mapped static analysis -> signed PDF evidence.\n\nThe agent does not report what it cannot show in source.\n\nNanoClone Systems",
        ],
    },
    {
        "slug": "search-rotation",
        "title": "Anti-stagnation in query surfaces",
        "linkedin": """A discovery system that reuses the same search queries decays within weeks. Results harden, coverage collapses, and the pipeline starves silently. We treat query rotation as a first-class engineering problem.

Current design: ~40 candidate queries across GitHub code and repository search — dependency-bot activity, framework-specific manifests, topic tags, ecosystem signals. Each day, a hash of the date selects a subset. Same day, same queries. Different day, different surface. Deterministic and auditable; no random seed stored anywhere.

Every result is cross-checked against a seen-set so the agent never spends compute on a repository it has already qualified. Rate-limit discipline is built in: bounded concurrency, token-budget accounting per cycle, and a hard stop when the daily budget is exhausted.

The failure mode this prevents is the one every lead-gen vendor ships with: a static list purchased once, depreciating daily, sold as "AI-powered discovery." Ours is a rotating instrument. It costs nothing to maintain because it runs as a scheduled job on infrastructure we already own.

{seen_total} repositories seen to date. {qualified} qualified. The rotation is why the funnel is still moving.

Renaat Sibanda
Founder, NanoClone Systems""",
        "farcaster": """Query rotation is the difference between a discovery engine and a decaying spreadsheet.

~40 seeded GitHub queries. Daily hash picks the subset. Same date, same surface — deterministic, auditable, no stored seed.

Cross-checked against a seen-set: zero reprocessing. Bounded concurrency, per-cycle token budgets, hard stop.

Static query lists are what lead-gen vendors sell as "AI discovery." They are purchased once and depreciate daily. Rotation is a scheduled job. Maintenance cost: zero.

{seen_total} seen. {qualified} qualified.

NanoClone Systems""",
        "x_thread": [
            "Static search queries decay. We rotate {pct:.2f}% of discovery surface daily via date-hash selection over ~40 seeded GitHub queries.\n\nDeterministic. Auditable. No stored seed.",
            "Every result cross-checked against a seen-set. Zero reprocessing. Token budgets enforced per cycle.\n\n{seen_total} repositories seen. {qualified} qualified.\n\nThe list is a living instrument, not a purchased spreadsheet.",
        ],
    },
    {
        "slug": "proof-led-commerce",
        "title": "Evidence-before-payment architecture",
        "linkedin": """Selling security work is a trust problem dressed as a sales problem. Our resolution is architectural: the customer sees the findings before money moves.

Flow: a public repository enters the pipeline, the agent scans it, and the operator receives a sanitized, anonymized proof artifact — the actual finding classes, mechanisms, and severity distribution of their own codebase — at no cost. The commercial offers attach after the evidence exists: a fixed-scope remediation engagement or a continuous monitoring retainer, both settled through Stripe or directly in USDC over Base via x402.

Why this holds economically: the scan is automated, so the free tier costs compute, not labor. The remediation deliverable is a verified patch plus a signed PDF report with a 48-hour SLA. Cancellation is self-serve — email with a fixed subject line, or the Stripe portal. No retention theater.

The buyer psychology is inverted from the standard audit sale. They are not funding a promise. They are purchasing execution on evidence they already hold.

Renaat Sibanda
Founder, NanoClone Systems""",
        "farcaster": """Standard security sale: pay first, receive findings later. Trust problem, sold as a sales problem.

Our inversion: scan is automated -> evidence ships free -> commerce attaches after.

Remediation: verified patch + signed PDF, 48h SLA. Monitoring: monthly retainer. Settlement: Stripe or USDC on Base via x402.

Free tier costs compute, not labor. That is the entire economic unlock.

The buyer is not funding a promise. They are purchasing execution on evidence they already hold.

NanoClone Systems""",
        "x_thread": [
            "The free tier in our security pipeline costs compute, not labor.\n\nThat single fact inverts the entire audit sale: evidence ships before payment. Always.",
            "Automated scan -> anonymized proof artifact -> fixed-scope remediation ($750, 48h SLA) or monitoring retainer.\n\nStripe or USDC on Base via x402.\n\nBuyers fund execution, not promises.",
        ],
    },
    {
        "slug": "suppression-mesh",
        "title": "The suppression mesh",
        "linkedin": """Outbound systems fail quietly. A bounced address keeps getting mailed, domain reputation degrades, and the operator finds out weeks later from a deliverability report. We closed that loop end-to-end.

Architecture: Resend webhook (signed with svix verification) receives bounce, complaint, and click-suppression events. The Cloud Run service validates the signature, writes the event to a suppression store on GCS — direct JSON API calls with metadata-server token auth, no heavyweight SDK in the container path. The local follow-up engine pulls /v1/pipeline/state on every cycle and merges cloud suppressions and paid-lead states into its decision set before any send is attempted.

One endpoint. One store. Three consumers: the live outreach service, the follow-up engine, and the payment webhook that mirrors closed-won events into the same state.

The property this buys: the agent cannot harass a prospect who bounced, complained, or paid. Not by policy — by construction. Suppression is checked in the same code path as scheduling, which means it cannot be forgotten in a refactor.

{followup1} first-stage and {followup2} second-stage follow-ups have shipped through this mesh without a single manual suppression check.

Renaat Sibanda
Founder, NanoClone Systems""",
        "farcaster": """Outbound fails quietly. Bounced addresses get remailed. Reputation degrades. You find out from a report weeks later.

Our mesh: Resend webhook (svix-signed) -> Cloud Run -> GCS suppression store (JSON API, metadata-token auth) -> local engine merges state every cycle before any send.

Three consumers, one store: live outreach, follow-up engine, payment webhooks.

The agent cannot mail a prospect who bounced, complained, or paid. Not by policy. By construction — suppression lives in the same code path as scheduling.

{followup1} stage-1, {followup2} stage-2 follow-ups shipped. Zero manual suppression checks.

NanoClone Systems""",
        "x_thread": [
            "Policy-based suppression breaks in refactors. Code-path suppression does not.\n\nOur follow-up engine checks bounce/complaint/payment state in the same path that decides scheduling. The agent physically cannot mail a suppressed prospect.",
            "Webhook (svix-signed) -> cloud store (JSON API, no SDK bloat) -> local merge every cycle.\n\n{followup1} + {followup2} follow-ups shipped. Zero manual suppression checks performed.",
        ],
    },
    {
        "slug": "deterministic-followup",
        "title": "The follow-up state machine",
        "linkedin": """Human follow-up discipline is a myth. Pipelines leak at exactly the point where memory is required. We replaced memory with a state machine.

Design: every qualified lead is written to a durable state file the moment first-touch ships. Stage-1 follow-up fires on a fixed horizon. Stage-2 follows. Each transition records a timestamp and an audit entry. A dry-run mode computes the due-set without sending. A forced-send mode exists for operator-approved batches and requires an explicit target list — it cannot fire blindly.

Before any send, the engine reconciles against pipeline state pulled from the cloud store: suppressions, paid leads, and closed-won repos are removed from the candidate set in memory, not by deleting history. The audit log records stage, repo, recipient, and outcome per attempt.

Current throughput: {followup1} leads through stage 1, {followup2} through stage 2. The machine runs as a scheduled job at 10:00 daily. Nobody remembers anything. Nothing leaks.

This is the difference between an outreach "tool" and an autonomous construct: the state lives in files the operator can audit, diff, and restore. Not in a SaaS dashboard you rent.

Renaat Sibanda
Founder, NanoClone Systems""",
        "farcaster": """Follow-up discipline as a human trait is a myth. Pipelines leak where memory is required.

Our construct: durable state file at first-touch. Stage-1, stage-2 on fixed horizons. Timestamps and audit entries per transition. Dry-run computes the due-set without sending. Forced-send requires an explicit target list.

Pre-send reconciliation against cloud pipeline state: suppressions, paid, closed-won removed in memory. History preserved.

{followup1} through stage 1. {followup2} through stage 2. Scheduled 10:00 daily. Nobody remembers anything. Nothing leaks.

State lives in auditable files. Not a rented dashboard.

NanoClone Systems""",
        "x_thread": [
            "An outreach system without durable per-lead state is a leaky bucket with a CRM skin.\n\nOurs: state file at first-touch, fixed-horizon stage transitions, audit entry per attempt, dry-run mode, explicit-list forced sends.",
            "{followup1} leads stage-1. {followup2} stage-2. 10:00 daily job. Zero human memory involved.\n\nState in diffable files, not a rented dashboard.",
        ],
    },
    {
        "slug": "dual-seat-approval",
        "title": "One queue, two approval surfaces",
        "linkedin": """Autonomy without a kill-seat is a liability. Every publishable action in our marketing pipeline routes through a single approval queue, and that queue has two surfaces: a Telegram bot and a desktop console styled as an operations deck.

Mechanics: content generators append queue entries to a shared state file — nothing publishes on generation. Each entry carries a kind, a payload, and a status. The approval surfaces read the same file. Approving from either surface runs the identical publish path: signed Farcaster cast via an approved signer key, with X and LinkedIn payloads delivered to the operator for manual posting, because those platforms' posting APIs are not open to us.

Liveness is handled by a heartbeat file written by the daemon each poll cycle. The deck reads heartbeat age; stale heartbeat turns the status pill red. A dead daemon is visible in seconds, not discovered when a tap freezes.

The engineering principle: one source of truth, two windows onto it, and a publish path so shared that surfaces cannot diverge in behavior. {queue_total} entries have passed through this design.

Renaat Sibanda
Founder, NanoClone Systems""",
        "farcaster": """Autonomy without a kill-seat is a liability.

Our marketing pipeline: generators write to one queue file. Nothing publishes on generation. Two approval surfaces read it — Telegram bot, desktop operations deck. Same file, same publish path, zero divergence.

Publish = signed Farcaster cast via approved signer key. X/LinkedIn payloads delivered to the operator for manual posting — those APIs are not open to us, and pretending otherwise would be theater.

Liveness: heartbeat file per daemon cycle. Deck reads age. Stale = red pill. A dead daemon is visible in seconds.

{queue_total} entries through the design. One truth, two windows.

NanoClone Systems""",
        "x_thread": [
            "Nothing in our marketing pipeline publishes on generation. Everything routes through one queue file with two approval surfaces: Telegram and a desktop ops deck.\n\nSame truth. Two windows. One publish path.",
            "Farcaster casts sign through an approved signer key. X/LinkedIn deliver as payloads for manual posting — we don't fake APIs we don't have.\n\nDaemon heartbeat gates the deck's status pill. Dead daemon = visible in seconds.",
        ],
    },
    {
        "slug": "shadow-audit",
        "title": "The marketing engine that reads code",
        "linkedin": """Most security marketing is written by people who have never opened the repository. Our content pipeline inverts that: the case studies are generated from actual scan output.

Weekly job: the shadow-audit construct selects a recent qualified repository from the queue and seen-set, renders the finding set into an anonymized case study — protocol and entity names redacted, CWE mappings preserved, severity distribution intact — then drafts platform-native posts from that artifact: an X thread, a Farcaster cast, a LinkedIn long-form. The draft enters the approval queue. Nothing publishes without a human seat.

The anonymization is structural, not editorial: entity names are replaced by deterministic placeholders at render time, so a leak of the draft cannot identify the scanned party. The findings themselves are real. The story is true. The target is not named.

This is what it means to position an agent as the product: the marketing engine is itself an autonomous construct reading live code, not a content calendar filled by guesswork.

Renaat Sibanda
Founder, NanoClone Systems""",
        "farcaster": """Security marketing written by people who have never opened the repository. Common. Useless.

Ours: weekly shadow-audit construct pulls a recent qualified repo, renders findings into an anonymized case study — entity names deterministic placeholders, CWE mappings and severity intact — then drafts X thread, Farcaster cast, LinkedIn long-form from that artifact.

Approval queue. Human seat required. No exceptions.

Anonymization is structural, not editorial. Findings are real. Target is not named.

The marketing engine is itself an autonomous construct reading live code.

NanoClone Systems""",
        "x_thread": [
            "Our content pipeline reads code, not briefs.\n\nWeekly job: qualified repo -> anonymized case study (CWE-mapped, severity-intact, entity names redacted at render) -> platform drafts -> approval queue.",
            "Anonymization is structural: deterministic placeholders replace entities at render time. Findings real. Target unnamed.\n\nThe marketing engine is itself an autonomous construct.",
        ],
    },
    {
        "slug": "sovereign-fleet",
        "title": "Operating cadence of a one-person agent fleet",
        "linkedin": """The question founders ask first is headcount. The correct question is cadence: what runs while you sleep, and what requires a human seat.

Current schedule on our infrastructure: 08:00 discovery construct sweeps rotated queries and writes qualified leads to the queue. 09:00 remediation outreach dispatches. 10:00 follow-up state machine reconciles and ships stage transitions. Mondays 11:00, the content pipeline generates a case study and a code-drop draft, both landing in approval surfaces. Live service on Cloud Run handles webhooks — payments, suppression, pipeline state — with stores on GCS accessed via metadata-token auth.

One founder. Zero marketing headcount. Overhead is compute and API meters.

Every scheduled job is auditable: run logs, state files, email audit records. When something ships, there is a file that says who, what, when. When something must not ship, there is a queue entry with a red button on a desktop console.

This is the operating model Nanoclone Systems sells as its example, not just its product: sovereign infrastructure, deterministic constructs, one human holding the kill-seat.

Renaat Sibanda
Founder, NanoClone Systems""",
        "farcaster": """One-person agent fleet. Current cadence:

08:00 discovery sweep (rotated queries, qualified leads to queue)
09:00 remediation outreach
10:00 follow-up state machine, stage transitions
Mon 11:00 content pipeline -> approval surfaces
Cloud Run webhooks: payments, suppression, pipeline state. GCS stores via metadata-token auth.

Zero marketing headcount. Overhead: compute and API meters.

Every job auditable — run logs, state files, email audit records. Everything unshippable has a queue entry and a red button on a desktop console.

Sovereign infrastructure. Deterministic constructs. One human at the kill-seat.

NanoClone Systems""",
        "x_thread": [
            "Operating cadence, one founder, zero marketing headcount:\n\n08:00 discovery. 09:00 outreach. 10:00 follow-up machine. Mon 11:00 content pipeline. Webhooks live 24/7.\n\nOverhead: compute and API meters.",
            "Every job writes an audit file. Everything unshippable routes to a queue with a red button on a desktop console.\n\nSovereign infrastructure. Deterministic constructs. One human at the kill-seat.",
        ],
    },
]


def pick_topic(override: str = "") -> dict:
    if override:
        for t in TOPICS:
            if t["slug"] == override:
                return t
        raise SystemExit(f"unknown topic '{override}' — available: "
                         + ", ".join(t["slug"] for t in TOPICS))
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    digest = hashlib.sha256(day.encode()).digest()
    return TOPICS[digest[0] % len(TOPICS)]


def render(topic: dict, stats: dict) -> dict:
    fmt = dict(stats)
    fmt["pct"] = (stats["qualified"] / max(stats["seen_total"], 1)) * 100
    return {
        "slug": f"bip_{topic['slug']}_{datetime.now(timezone.utc).strftime('%Y%m%d')}",
        "kind_label": "CODE DROP",
        "title": topic["title"],
        "rating": "CODE",
        "x_thread": [t.format(**fmt) for t in topic["x_thread"]],
        "farcaster": topic["farcaster"].format(**fmt),
        "linkedin": topic["linkedin"].format(**fmt),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def save_draft(draft: dict) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    md = [f"# Build in Public — {draft['slug']}", "",
          f"Title: {draft['title']}", "", "## X thread", ""]
    for i, t in enumerate(draft["x_thread"], 1):
        md += [f"### Tweet {i}", "", t, ""]
    md += ["## Farcaster cast", "", draft["farcaster"], "",
           "## LinkedIn post", "", draft["linkedin"], ""]
    path = REPORT_DIR / f"{draft['slug']}.md"
    path.write_text("\n".join(md), encoding="utf-8")
    (REPORT_DIR / f"{draft['slug']}.social.json").write_text(
        json.dumps(draft, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def main() -> None:
    p = argparse.ArgumentParser(description="PYRESEC Build-in-Public engine")
    p.add_argument("--topic", default="", help="force a topic slug")
    p.add_argument("--print-only", action="store_true",
                   help="print drafts only — do not queue")
    args = p.parse_args()

    stats = live_stats()
    topic = pick_topic(args.topic)
    draft = render(topic, stats)
    path = save_draft(draft)
    pct = stats["qualified"] / max(stats["seen_total"], 1) * 100

    print(f"[bip] draft: {path}")
    print(f"[bip] topic: {topic['slug']} — {topic['title']}")
    print("\n--- X thread ---")
    for i, t in enumerate(draft["x_thread"], 1):
        print(f"\n[tweet {i}/{len(draft['x_thread'])} | {len(t)} chars]\n{t}")
    print(f"\n--- Farcaster ({len(draft['farcaster'].encode())} bytes) ---\n"
          f"{draft['farcaster']}")
    print(f"\n--- LinkedIn ---\n{draft['linkedin']}")
    print(f"\n[bip] stats: seen={stats['seen_total']} qualified={stats['qualified']} "
          f"({pct:.2f}%) fu1={stats['followup1']} fu2={stats['followup2']}")

    if args.print_only:
        print("\n[bip] print-only — nothing queued.")
    else:
        import social_pipeline as sp
        qid = sp.queue_for_telegram(draft, kind="buildinpublic")
        print(f"\n[bip] queued (qid={qid}) — approve in Telegram or the Social Deck.")


if __name__ == "__main__":
    main()
