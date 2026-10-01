#!/usr/bin/env python3
"""PYRESEC Continuous Monitoring — weekly delta run.

Reads scripts/monitor_registry.json, scans each active public repository,
diffs findings against the stored baseline, writes a markdown report to
reports/monitoring_delta_YYYY-MM-DD.md, and updates the registry.

This is the concierge Phase-1 runner: public main/master branches only.
Private repos require a future GitHub App/PAT integration.
"""

import os
import sys
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import probe

REGISTRY_FILE = Path(__file__).resolve().parent / "monitor_registry.json"
REPORTS_DIR = ROOT / "reports"
REPORTS_DIR.mkdir(exist_ok=True)


def load_registry() -> dict:
    if REGISTRY_FILE.exists():
        try:
            return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"subscriptions": []}


def save_registry(data: dict):
    REGISTRY_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def finding_id(f: dict) -> str:
    """Stable key for diffing findings across runs."""
    return "|".join([
        str(f.get("severity", "?")).upper(),
        str(f.get("type", "?")),
        str(f.get("line_number") or f.get("package") or ""),
        str(f.get("cwe") or f.get("cve") or ""),
    ])


def normalize_findings(scan: dict) -> list[dict]:
    """Flatten and sanitize findings for JSON storage + diffing."""
    out = []
    sources = [
        scan.get("sast_findings") or [],
        scan.get("sca_findings") or [],
        scan.get("gas_findings") or [],
    ]
    for src in sources:
        for f in src:
            out.append({
                "severity": str(f.get("severity", "?")).upper(),
                "type": f.get("type", "finding"),
                "cwe": f.get("cwe") or f.get("cve") or "",
                "line_number": f.get("line_number") or "",
                "package": f.get("package") or "",
                "description": str(f.get("description", ""))[:220],
            })
    return out


def run_one(sub: dict) -> dict:
    """Scan a single subscription and update its baseline."""
    repo = sub.get("repo", "")
    branch = sub.get("branch", "main")
    print(f"[monitor] scanning {repo} (branch: {branch}) ...")

    code = probe.fetch_repo_main_file(repo)
    if not code:
        return {
            "repo": repo,
            "branch": branch,
            "error": "no scannable entry file or repository unavailable",
        }

    scan = probe.local_scan(code)
    findings = normalize_findings(scan)
    baseline = sub.get("last_scan") or []
    baseline_ids = {finding_id(f) for f in baseline}
    current_ids = {finding_id(f) for f in findings}

    new = [f for f in findings if finding_id(f) not in baseline_ids]
    resolved = [f for f in baseline if finding_id(f) not in current_ids]

    sub["last_scan"] = findings
    sub["last_scan_at"] = datetime.now(timezone.utc).isoformat()

    return {
        "repo": repo,
        "branch": branch,
        "total": len(findings),
        "new": new,
        "resolved": resolved,
        "raw_scan": scan,
    }


def generate_markdown(results: list[dict]) -> str:
    """Build the weekly markdown delta report."""
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [
        f"# PYRESEC Continuous Monitoring — Weekly Delta Report ({date})",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()} UTC",
        "",
    ]

    for r in results:
        if "error" in r:
            lines += [f"## {r['repo']} (`{r['branch']}`)", "", f"⚠️ {r['error']}", ""]
            continue

        lines += [
            f"## {r['repo']} (`{r['branch']}`)",
            "",
            f"- Total findings: {r['total']}",
            f"- New since last scan: {len(r['new'])}",
            f"- Resolved since last scan: {len(r['resolved'])}",
            "",
        ]

        if r["new"]:
            lines.append("### New findings")
            for f in r["new"]:
                loc = f"line {f['line_number']}" if f.get("line_number") else (f.get("package") or "")
                lines.append(f"- **[{f['severity']}]** {f['type']} {f['cwe']} ({loc})")
                if f.get("description"):
                    lines.append(f"  - {f['description']}")
            lines.append("")

        if r["resolved"]:
            lines.append("### Resolved findings")
            for f in r["resolved"]:
                loc = f"line {f['line_number']}" if f.get("line_number") else (f.get("package") or "")
                lines.append(f"- **[{f['severity']}]** {f['type']} {f['cwe']} ({loc})")
            lines.append("")

    lines += [
        "---",
        "",
        "Scope: public main/master branches only. Critical/High regressions should trigger immediate remediation review.",
    ]
    return "\n".join(lines)


def main():
    data = load_registry()
    subs = [s for s in data.get("subscriptions", []) if s.get("active", True)]

    if not subs:
        print("[monitor] no active subscriptions")

    results = []
    for sub in subs:
        results.append(run_one(sub))

    md = generate_markdown(results)
    report_path = REPORTS_DIR / f"monitoring_delta_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.md"
    report_path.write_text(md, encoding="utf-8")

    save_registry(data)

    total_new = sum(len(r.get("new", [])) for r in results)
    print(f"[monitor] active subscriptions: {len(subs)}")
    print(f"[monitor] new findings: {total_new}")
    print(f"[monitor] report written: {report_path}")


if __name__ == "__main__":
    main()
