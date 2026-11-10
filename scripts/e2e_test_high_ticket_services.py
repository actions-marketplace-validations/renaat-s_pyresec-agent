#!/usr/bin/env python3
"""End-to-end functional test of PYRESEC high-ticket services.

Bypasses Stripe/x402 payment gates by calling the same engine functions the
paid endpoints use. Uses the live Nanoclone-Systems repository as the target
repo to prove the pipeline works against real GitHub code.

Tests:
  1. Continuous Monitoring  -> weekly delta scan + markdown report
  2. Proof-Led Remediation  -> deep audit + LLM remediation + signed PDF
"""

import os
import sys
import json
import asyncio
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# Force UTF-8 output on Windows consoles for status markers and report previews.
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import groq
import probe
from agent_controller import (
    deep_audit_with_llm,
    remediate_code_with_llm,
)
from report_generator import generate_report

REPO = "renaat-s/Nanoclone-Systems"
REPO_URL = f"https://github.com/{REPO}"
REPORTS_DIR = ROOT / "reports"


def banner(title: str):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70 + "\n")


def test_continuous_monitoring():
    """Run one weekly monitoring cycle against the Nanoclone-Systems repo."""
    banner("TEST 1: CONTINUOUS MONITORING")

    registry_file = ROOT / "scripts" / "monitor_registry.json"
    registry = {"subscriptions": []}
    if registry_file.exists():
        try:
            registry = json.loads(registry_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    # Ensure a subscription exists for the test repo
    subs = registry.setdefault("subscriptions", [])
    existing = next((s for s in subs if s.get("repo") == REPO), None)
    if not existing:
        subs.append({
            "repo": REPO,
            "branch": "main",
            "active": True,
            "client": "Nanoclone Systems (E2E Test)",
            "contact": "info@nanoclonesystems.com",
        })
        print(f"[monitor] added subscription for {REPO}")
    else:
        existing["active"] = True
        print(f"[monitor] subscription for {REPO} already exists")

    registry_file.write_text(json.dumps(registry, indent=2), encoding="utf-8")

    # Import and run the actual monitoring engine
    import run_weekly_monitoring as mon
    mon.main()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report_path = REPORTS_DIR / f"monitoring_delta_{today}.md"
    if report_path.exists():
        print(f"\n[monitor] [PASS] report generated: {report_path}")
        print("--- preview ---")
        print(report_path.read_text(encoding="utf-8")[:1200])
        print("---")
        return True
    else:
        print(f"\n[monitor] [FAIL] expected report not found: {report_path}")
        return False


async def test_proof_led_remediation():
    """Run the full $500 engagement pipeline against real repo code."""
    banner("TEST 2: PROOF-LED REMEDIATION")

    groq_client = groq.Groq(api_key=os.getenv("GROQ_API_KEY"))

    # Fetch real code from the Nanoclone-Systems repo
    code = probe.fetch_repo_main_file(REPO)
    if not code:
        print(f"[remediation] ❌ could not fetch code from {REPO}")
        return False

    print(f"[remediation] fetched {len(code)} bytes from {REPO}")

    # Inject a small, realistic vulnerability block so the remediation path
    # is exercised end-to-end (the real repo is a clean React/Vite site).
    # This simulates a paying user submitting their own vulnerable module.
    vulnerable_block = """
# --- test injection: realistic vulnerability sample ---
import os
import pickle

def handle_request(user_cmd, user_blob):
    password = "hunter2"
    os.system(user_cmd)
    return pickle.loads(user_blob)
"""
    code += vulnerable_block

    print("[remediation] running deep audit with LLM (qwen/qwen3.8-27b)...")
    audit = await deep_audit_with_llm(code, groq_client)
    print(f"[remediation] audit complete: {audit['total_sast']} SAST, {audit['total_sca']} SCA, {audit['total_gas']} gas")

    print("[remediation] running LLM remediation...")
    remediation = await remediate_code_with_llm(code, groq_client)
    patched = (remediation.get("remediation") or {}).get("patched_code")
    changes = (remediation.get("remediation") or {}).get("changes_made", [])
    print(f"[remediation] remediation complete: patched_code present={bool(patched)}, changes={len(changes)}")

    # Merge into the canonical scan shape the report generator expects
    scan = {
        **audit,
        "remediation": remediation.get("remediation"),
        "patched_code": patched,
        "changes_made": changes,
        "security_notes": (remediation.get("remediation") or {}).get("security_notes", []),
        "total_vulnerabilities": remediation.get("total_vulnerabilities", 0),
        "agent": os.getenv("AGENT_ADDRESS", "pyresec-agent-test"),
        "model": audit.get("model", "qwen/qwen3.8-27b"),
    }

    meta = {
        "client": "Nanoclone Systems",
        "repo_url": REPO_URL,
        "engagement": "Proof-Led Remediation (E2E Functional Test)",
        "contact": "info@nanoclonesystems.com",
        "upsell": "Activate Continuous Monitoring to catch regressions on this branch.",
    }

    out_dir = tempfile.mkdtemp(prefix="pyresec_e2e_")
    pdf_path = generate_report(scan, meta, out_dir=out_dir)
    print(f"\n[remediation] [PASS] PDF report generated: {pdf_path}")

    # Copy the PDF to the standard reports directory for easy access
    final_path = REPORTS_DIR / f"PYRESEC-e2e-Nanoclone-Systems-{datetime.now(timezone.utc).strftime('%Y%m%d')}.pdf"
    import shutil
    shutil.copy(pdf_path, final_path)
    print(f"[remediation] [PASS] copied to: {final_path}")

    # Sanity checks
    checks = {
        "audit has findings": audit["total_sast"] + audit["total_sca"] + audit["total_gas"] > 0,
        "LLM analysis produced": bool(audit.get("llm_analysis")),
        "patched code produced": bool(patched),
        "PDF exists": final_path.exists(),
        "PDF > 10KB": final_path.stat().st_size > 10_000,
    }
    for name, ok in checks.items():
        print(f"[remediation]   [{'PASS' if ok else 'FAIL'}] {name}")

    return all(checks.values())


async def main():
    print("PYRESEC HIGH-TICKET SERVICE END-TO-END TEST")
    print(f"Target repo: {REPO}")
    print(f"Target repo URL: {REPO_URL}")
    print(f"Model under test: qwen/qwen3.8-27b")

    ok_monitor = test_continuous_monitoring()
    ok_remedy = await test_proof_led_remediation()

    banner("TEST SUMMARY")
    print(f"Continuous Monitoring: {'PASS' if ok_monitor else 'FAIL'}")
    print(f"Proof-Led Remediation: {'PASS' if ok_remedy else 'FAIL'}")
    print(f"Overall: {'PASS - both high-ticket services are functional' if ok_monitor and ok_remedy else 'FAIL - see above'}")
    sys.exit(0 if ok_monitor and ok_remedy else 1)


if __name__ == "__main__":
    asyncio.run(main())
