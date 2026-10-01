#!/usr/bin/env python3
"""PYRESEC Content Engine — turn a public repo scan into a proof-led case study.

Generates:
  • Markdown case study (reports/content_case_study_<repo>_<date>.md)
  • Optional PDF report artifact
  • X / Farcaster / LinkedIn post copy

Requires CRITICAL or HIGH findings — low-severity repos make weak content.

Usage:
    python scripts/content_engine.py owner/repo
    python scripts/content_engine.py owner/repo --anonymize --patch --pdf
"""

import os
import sys
import json
import asyncio
import argparse
import io
from datetime import datetime, timezone
from pathlib import Path

# Windows console: allow unicode in output (CMD defaults to cp1252)
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import groq
import probe
import playbooks
from report_generator import generate_report

REPORTS_DIR = ROOT / "reports"
REPORTS_DIR.mkdir(exist_ok=True)


def _window(lines: list[str], center: int, radius: int = 4) -> str:
    start = max(0, center - radius)
    end = min(len(lines), center + radius + 1)
    out = []
    for i in range(start, end):
        marker = ">>> " if i == center else "    "
        out.append(f"{marker}{i + 1:3}: {lines[i]}")
    return "\n".join(out)


def _build_social_copy(repo: str, findings: list[dict], anonymize: bool) -> dict:
    display = "Protocol X" if anonymize else repo
    top = findings[0] if findings else {}
    sev = (top.get("severity") or "?").upper()
    cwe = top.get("cwe") or top.get("cve") or ""
    line = top.get("line_number") or "?"
    ftype = top.get("type", "finding")

    x = (
        f"We scanned {display} with PYRESEC.\n"
        f"Top hit: [{sev}] {ftype} {cwe} @ line {line}.\n\n"
        f"Disclosure is free. Verified patch + signed PDF: $750.\n"
        f"Monitoring retainer: $495/mo.\n\n"
        f"Evidence-first security audits -> https://pyresec.io/services"
    )

    farcaster = (
        f"Ran PYRESEC on {display}: {sev} rating.\n"
        f"{ftype} {cwe} @ line {line}.\n"
        f"Free baseline, $750 fix, $495/mo monitoring."
    )

    linkedin = (
        f"Case study: {display}\n\n"
        f"Our AI security engine flagged a [{sev}] {ftype} ({cwe}) at line {line}. "
        f"We disclose the proof for free — because funded teams should see evidence before they buy.\n\n"
        f"For {display}, a verified patch + signed assessment PDF runs $750, or continuous monitoring at $495/mo.\n\n"
        f"#Web3Security #SmartContracts #AIAgent #CodeAudit"
    )

    return {"x": x, "farcaster": farcaster, "linkedin": linkedin}


def _generate_patch_section(code: str, finding: dict, patched_code: str) -> str:
    line_no = finding.get("line_number")
    if not line_no or not patched_code:
        return ""
    orig_lines = code.splitlines()
    patch_lines = patched_code.splitlines()
    idx = max(0, line_no - 1)
    orig_window = _window(orig_lines, idx, 3)
    patch_window = _window(patch_lines, idx, 3) if idx < len(patch_lines) else "(patch location unavailable)"
    return f"""### Before / After

**Before (vulnerable):**
```
{orig_window}
```

**After (patched):**
```
{patch_window}
```
"""


def build_case_study(repo: str, code: str, scan: dict, anonymize: bool = False,
                     patched_code: str = None) -> str:
    display_repo = "Protocol X" if anonymize else repo
    rating = playbooks.risk_rating(scan)
    findings = playbooks.top_findings(scan, 3)
    counts = {}
    for f in (scan.get("sast_findings") or []) + (scan.get("sca_findings") or []):
        sev = (f.get("severity") or "?").upper()
        counts[sev] = counts.get(sev, 0) + 1
    count_line = ", ".join(f"{v} {k.lower()}" for k, v in counts.items()) or "clean"

    finding_blocks = []
    for i, f in enumerate(findings, 1):
        sev = (f.get("severity") or "?").upper()
        cwe = f.get("cwe") or f.get("cve") or ""
        loc = f"line {f['line_number']}" if f.get("line_number") else (f.get("package") or "")
        finding_blocks.append(
            f"**[{i}] [{sev}] {f.get('type', 'finding')} {cwe}** ({loc})\n"
            f"> {f.get('description', '')}\n"
        )
        if patched_code and i == 1:
            finding_blocks.append(_generate_patch_section(code, f, patched_code))

    social = _build_social_copy(repo, findings, anonymize)

    md = f"""# PYRESEC Case Study: {display_repo}

**Published:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}  
**Source:** `{'redacted' if anonymize else repo}`  
**Risk rating:** {rating}  
**Finding summary:** {count_line}

---

## The Setup

{display_repo} is a public codebase we scanned with the same PYRESEC engine that powers our paid engagements. No account, no payment, no NDA — just evidence.

## What We Found

{chr(10).join(finding_blocks)}

## What This Means

A [{rating}] rating in a production codebase is not a theoretical concern. It is an exploitable condition that should be patched and documented before the next release, especially if the code touches user funds, authentication, or deployment pipelines.

## PYRESEC Engagement Options

| Service | Price | Deliverable |
|---|---|---|
| Proof-Led Remediation | $750 one-time | Verified patch + signed PDF report |
| Continuous Monitoring | $495/mo | Weekly re-scan, diff reports, CVE watch |

Get the free baseline first: https://pyresec.io/services

---

## Social Copy

### X / Twitter
```
{social['x']}
```

### Farcaster
```
{social['farcaster']}
```

### LinkedIn
```
{social['linkedin']}
```
"""
    return md


def main():
    parser = argparse.ArgumentParser(description="Generate a PYRESEC case study from a public repo")
    parser.add_argument("repo", help="GitHub owner/repo, e.g. uniswap/uniswap-v3-core")
    parser.add_argument("--anonymize", action="store_true", help="Redact the repo name as 'Protocol X'")
    parser.add_argument("--patch", action="store_true", help="Run LLM remediation to include before/after patch")
    parser.add_argument("--pdf", action="store_true", help="Also generate a signed PDF report artifact")
    args = parser.parse_args()

    print(f"[content] fetching {args.repo} ...")
    code = probe.fetch_repo_main_file(args.repo)
    if not code:
        raise SystemExit(f"[content] no scannable entry file for {args.repo}")

    print("[content] running local scan ...")
    scan = probe.local_scan(code)
    rating = playbooks.risk_rating(scan)
    if rating not in ("CRITICAL", "HIGH"):
        raise SystemExit(f"[content] {args.repo} rated {rating} — skipping (need CRITICAL/HIGH for a strong case study)")

    patched_code = None
    if args.patch:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            print("[content] warning: GROQ_API_KEY not set, patch generation skipped")
        else:
            print("[content] generating LLM patch ...")
            client = groq.Groq(api_key=api_key)
            result = asyncio.run(
                __import__("agent_controller").remediate_code_with_llm(code, client)
            )
            patched_code = result.get("remediation", {}).get("patched_code")
            if patched_code:
                print(f"[content] patch generated ({len(patched_code)} chars)")
            else:
                print("[content] warning: LLM did not return patched_code")

    md = build_case_study(args.repo, code, scan, args.anonymize, patched_code)
    slug = args.repo.replace("/", "_")
    date = datetime.now(timezone.utc).strftime("%Y%m%d")
    md_path = REPORTS_DIR / f"content_case_study_{slug}_{date}.md"
    md_path.write_text(md, encoding="utf-8")
    print(f"[content] markdown: {md_path}")

    if args.pdf:
        pdf_path = REPORTS_DIR / f"content_case_study_{slug}_{date}.pdf"
        generate_report(scan, repo_name=args.repo, output_path=str(pdf_path))
        print(f"[content] pdf: {pdf_path}")


if __name__ == "__main__":
    main()
