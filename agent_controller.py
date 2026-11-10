import hashlib
import json
import re

SAST_PATTERNS = {
    "SQL_INJECTION": {"patterns": [r"execute\(.*%s", r"execute\(.*\+", r"cursor\.execute.*f\"", r"\.format\(.*SELECT"], "severity": "HIGH", "cwe": "CWE-89", "description": "Potential SQL injection"},
    "XSS": {"patterns": [r"innerHTML\s*=", r"document\.write\(", r"eval\("], "severity": "HIGH", "cwe": "CWE-79", "description": "Potential XSS vulnerability"},
    "HARDCODED_SECRET": {"patterns": [r"password\s*=\s*[\"'][^\"']+[\"']", r"api_key\s*=\s*[\"'][^\"']+[\"']"], "severity": "CRITICAL", "cwe": "CWE-798", "description": "Hardcoded secret detected"},
    "COMMAND_INJECTION": {"patterns": [r"os\.system\(", r"subprocess\.call\(.*shell\s*=\s*True", r"eval\(", r"exec\("], "severity": "CRITICAL", "cwe": "CWE-78", "description": "Potential command injection"},
    "PATH_TRAVERSAL": {"patterns": [r"\.\.\/", r"\.\.\\", r"open\(.*\+"], "severity": "MEDIUM", "cwe": "CWE-22", "description": "Potential path traversal"},
    "INSECURE_DESERIALIZATION": {"patterns": [r"pickle\.load\(", r"yaml\.load\((?!.*Loader)"], "severity": "HIGH", "cwe": "CWE-502", "description": "Insecure deserialization"},
}

SCA_RISK_PATTERNS = [
    {"package": "lodash", "versions": "<4.17.21", "cve": "CVE-2021-23337"},
    {"package": "axios", "versions": "<0.21.1", "cve": "CVE-2020-28168"},
    {"package": "flask", "versions": "<2.2.5", "cve": "CVE-2023-30861"},
    {"package": "requests", "versions": "<2.31.0", "cve": "CVE-2023-32681"},
]

GAS_PATTERNS = {
    "LOOP_INCREMENT": {"pattern": r"for\s*\(\s*uint\s+\w+\s*=\s*0\s*;\s*\w+\s*<", "severity": "LOW", "description": "Use unchecked increment for gas savings"},
    "STORAGE_IN_LOOP": {"pattern": r"for\s*\(.*\)\s*\{[^}]*\bstorage\b", "severity": "MEDIUM", "description": "Storage writes inside loops are expensive"},
}

def compute_file_hash(content):
    return hashlib.sha256(content.encode()).hexdigest()

def run_sast_scan(code, full=False):
    findings = []
    lines = code.split("\n")
    patterns = SAST_PATTERNS if full else dict(list(SAST_PATTERNS.items())[:3])
    for vuln_type, config in patterns.items():
        for pat in config["patterns"]:
            for i, line in enumerate(lines, 1):
                if re.search(pat, line, re.IGNORECASE):
                    findings.append({"type": vuln_type, "severity": config["severity"], "cwe": config.get("cwe", "N/A"), "description": config["description"], "line_number": i, "line_content": line.strip()[:150]})
    findings.sort(key=lambda x: {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}.get(x["severity"], 4))
    return findings[:3] if not full else findings

def run_sca_scan(code):
    findings = []
    for risk in SCA_RISK_PATTERNS:
        if risk["package"].lower() in code.lower():
            findings.append({"type": "SCA_VULN", "severity": "HIGH", "cwe": "CWE-1395", "package": risk["package"], "cve": risk["cve"], "affected_versions": risk["versions"]})
    return findings

def run_gas_optimization_scan(code):
    findings = []
    lines = code.split("\n")
    for vuln_type, config in GAS_PATTERNS.items():
        for i, line in enumerate(lines, 1):
            if re.search(config["pattern"], line, re.IGNORECASE):
                findings.append({"type": f"GAS_{vuln_type}", "severity": config["severity"], "description": config["description"], "line_number": i, "line_content": line.strip()[:150]})
    return findings

async def quick_scan_with_llm(code, groq_client):
    file_hash = compute_file_hash(code)
    sast_findings = run_sast_scan(code, full=False)
    prompt = f"Run a fast security scan. Return exactly 3 bullet points covering the most critical risks.\n\nCODE:\n```python\n{code[:6000]}\n```\n\nRespond with ONLY 3 bullet points, each starting with \"- \". No preamble."
    completion = groq_client.chat.completions.create(model="qwen/qwen3.8-27b", messages=[{"role": "user", "content": prompt}], temperature=0.1, max_tokens=512)
    return {"file_hash": file_hash, "sast_findings": sast_findings, "llm_findings": completion.choices[0].message.content, "model": "qwen/qwen3.8-27b"}

async def deep_audit_with_llm(code, groq_client):
    file_hash = compute_file_hash(code)
    sast_findings = run_sast_scan(code, full=True)
    sca_findings = run_sca_scan(code)
    gas_findings = run_gas_optimization_scan(code)
    prompt = f"You are an expert security auditor. Perform an exhaustive audit.\n\nCODE:\n```python\n{code[:12000]}\n```\n\nRespond in strict JSON:\n{{\"risk_level\": \"LOW|MEDIUM|HIGH|CRITICAL\", \"summary\": \"Overall assessment\", \"owasp_findings\": [...], \"logic_flaws\": [...], \"recommendations\": [...]}}"
    completion = groq_client.chat.completions.create(model="qwen/qwen3.8-27b", messages=[{"role": "user", "content": prompt}], temperature=0.1, max_tokens=4096)
    llm_result = completion.choices[0].message.content
    try:
        json_match = re.search(r"\{[\s\S]*\}", llm_result)
        llm_analysis = json.loads(json_match.group()) if json_match else {"raw_response": llm_result}
    except json.JSONDecodeError:
        llm_analysis = {"raw_response": llm_result}
    return {"file_hash": file_hash, "sast_findings": sast_findings, "sca_findings": sca_findings, "gas_findings": gas_findings, "llm_analysis": llm_analysis, "total_sast": len(sast_findings), "total_sca": len(sca_findings), "total_gas": len(gas_findings), "model": "qwen/qwen3.8-27b"}

async def remediate_code_with_llm(code, groq_client):
    file_hash = compute_file_hash(code)
    sast_findings = run_sast_scan(code, full=True)
    sca_findings = run_sca_scan(code)
    gas_findings = run_gas_optimization_scan(code)
    prompt = f"You are an expert secure code engineer. Identify ALL vulnerabilities and generate a COMPLETE patched version.\n\nCODE:\n```python\n{code[:12000]}\n```\n\nRespond in strict JSON:\n{{\"vulnerabilities_found\": [...], \"patched_code\": \"COMPLETE fixed code\", \"changes_made\": [...], \"security_notes\": [...]}}"
    completion = groq_client.chat.completions.create(model="qwen/qwen3.8-27b", messages=[{"role": "user", "content": prompt}], temperature=0.1, max_tokens=8192)
    llm_result = completion.choices[0].message.content
    try:
        json_match = re.search(r"\{[\s\S]*\}", llm_result)
        remediation = json.loads(json_match.group()) if json_match else {"raw_response": llm_result, "patched_code": None}
    except json.JSONDecodeError:
        remediation = {"raw_response": llm_result, "patched_code": None}
    return {"file_hash": file_hash, "sast_findings": sast_findings, "sca_findings": sca_findings, "gas_findings": gas_findings, "remediation": remediation, "total_vulnerabilities": len(sast_findings) + len(sca_findings) + len(gas_findings), "model": "qwen/qwen3.8-27b"}
