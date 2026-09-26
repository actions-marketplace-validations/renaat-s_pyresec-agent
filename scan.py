import os
import sys
import json
import glob
import x402

CODE_PATH = os.environ.get("CODE_PATH", "./src")
TIER = os.environ.get("TIER", "quick-scan")
WALLET_KEY = os.environ.get("WALLET_KEY")
PYRESEC_URL = os.environ.get("PYRESEC_URL", "https://pyresec-agent-519576377065.us-central1.run.app")
FAIL_ON_FINDINGS = os.environ.get("FAIL_ON_FINDINGS", "true").lower() == "true"

ENDPOINT_MAP = {
    "quick-scan": "/v1/audit/quick-scan",
    "deep-repo": "/v1/audit/deep-repo",
    "remediate": "/v1/audit/remediate",
}


def collect_code(path):
    extensions = ("*.py", "*.js", "*.ts", "*.sol", "*.go", "*.rs", "*.java")
    files = []
    for ext in extensions:
        files.extend(glob.glob(os.path.join(path, "**", ext), recursive=True))

    combined = []
    for f in files:
        with open(f, "r", errors="ignore") as fh:
            content = fh.read()
            rel = os.path.relpath(f, path)
            combined.append(f"# File: {rel}\n{content}")

    return "\n\n".join(combined)


def main():
    if not WALLET_KEY:
        print("ERROR: X402_WALLET_KEY secret not set")
        sys.exit(1)

    code = collect_code(CODE_PATH)
    if not code.strip():
        print(f"WARNING: No source files found in {CODE_PATH}")
        sys.exit(0)

    endpoint = ENDPOINT_MAP.get(TIER)
    if not endpoint:
        print(f"ERROR: Unknown tier '{TIER}'. Use: quick-scan, deep-repo, or remediate")
        sys.exit(1)

    print(f"PYRESEC: Scanning {CODE_PATH} with tier {TIER}...")

    client = x402.Client(wallet_key=WALLET_KEY)
    response = client.post(
        f"{PYRESEC_URL}{endpoint}",
        json={"code": code}
    )

    result = response.json()

    with open("pyresec-results.json", "w") as f:
        json.dump(result, f, indent=2)

    print("PYRESEC: Scan complete. Results saved to pyresec-results.json")

    findings_count = 0

    if TIER == "quick-scan":
        findings = result.get("sast_findings", [])
        findings_count = len(findings)
        if findings:
            print(f"\n{'='*60}")
            print(f"PYRESEC: {findings_count} FINDINGS DETECTED")
            print(f"{'='*60}")
            for i, item in enumerate(findings, 1):
                print(f"\n{i}. [{item.get('severity', '?')}] {item.get('type', 'Unknown')}")
                print(f"   CWE: {item.get('cwe', 'N/A')}")
                print(f"   Line: {item.get('line', 'N/A')}")
                print(f"   {item.get('detail', '')}")
            print(f"\n{'='*60}")
        else:
            print("PYRESEC: No findings detected.")

    elif TIER == "deep-repo":
        total = result.get("total_findings", 0)
        findings_count = total
        sast = len(result.get("sast_findings", []))
        sca = len(result.get("sca_findings", []))
        gas = len(result.get("gas_findings", []))
        if total > 0:
            print(f"\n{'='*60}")
            print(f"PYRESEC: {total} FINDINGS (SAST={sast}, SCA={sca}, Gas={gas})")
            print(f"{'='*60}")
            print("Review pyresec-results.json for full details.")
        else:
            print("PYRESEC: No findings detected.")

    elif TIER == "remediate":
        vulns = result.get("total_vulnerabilities", 0)
        findings_count = vulns
        if vulns > 0:
            print(f"\nPYRESEC: {vulns} vulnerabilities remediated.")
            patched = result.get("patched_code")
            if patched:
                with open("pyresec-patched.py", "w") as f:
                    f.write(patched)
                print("Patched code saved to pyresec-patched.py")
        else:
            print("PYRESEC: No vulnerabilities found. Code is clean.")

    if FAIL_ON_FINDINGS and findings_count > 0:
        print(f"\nFAILED: {findings_count} findings detected. Review pyresec-results.json")
        sys.exit(1)


if __name__ == "__main__":
    main()
