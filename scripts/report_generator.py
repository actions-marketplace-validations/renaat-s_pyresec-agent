"""PYRESEC Report Generator â€” produces the client-facing PDF deliverable.

Turns a scan result (quick-scan / deep-repo / remediate response) into a
professional security assessment PDF suitable for high-ticket engagements.

Usage:
    from scripts.report_generator import generate_report
    path = generate_report(scan_result, {"client": "acme-dao", ...})
"""

import os
import re
import datetime
from typing import Optional

from fpdf import FPDF

FONT_DIR = r"C:\Windows\Fonts"
REPORT_DIR = "reports"

# Font fallbacks: Windows dev box first, then container/system fonts.
# Each entry: (directory, {family: {style: filename}})
_FONT_SETS = [
    (r"C:\Windows\Fonts", {
        "Arial": {"": "arial.ttf", "B": "arialbd.ttf", "I": "ariali.ttf"},
        "Mono": {"": "consola.ttf", "B": "consolab.ttf"},
    }),
    ("/usr/share/fonts/truetype/dejavu", {
        "Arial": {"": "DejaVuSans.ttf", "B": "DejaVuSans-Bold.ttf",
                  "I": "DejaVuSans-Oblique.ttf"},
        "Mono": {"": "DejaVuSansMono.ttf", "B": "DejaVuSansMono-Bold.ttf",
                 "I": "DejaVuSansMono-Oblique.ttf"},
    }),
    ("/usr/share/fonts/truetype/liberation", {
        "Arial": {"": "LiberationSans-Regular.ttf", "B": "LiberationSans-Bold.ttf",
                  "I": "LiberationSans-Italic.ttf"},
        "Mono": {"": "LiberationMono-Regular.ttf", "B": "LiberationMono-Bold.ttf",
                 "I": "LiberationMono-Italic.ttf"},
    }),
]

SEV_COLORS = {
    "CRITICAL": (176, 32, 48),
    "HIGH": (214, 92, 24),
    "MEDIUM": (196, 148, 16),
    "LOW": (78, 121, 167),
    "INFO": (110, 110, 110),
}
SEV_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}


def _sanitize(text) -> str:
    if text is None:
        return ""
    text = str(text)
    text = text.replace("\x00", "")
    return text


class _ReportPDF(FPDF):
    def __init__(self, ref: str, client: str):
        super().__init__(format="A4")
        self.ref = ref
        self.client = client
        self.set_auto_page_break(auto=True, margin=22)

    def header(self):
        if self.page_no() == 1:
            return
        self.set_font("Arial", "", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 6, f"PYRESEC Security Assessment  |  {self.client}  |  {self.ref}", align="L")
        self.ln(8)
        self.set_draw_color(220, 220, 220)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(4)

    def footer(self):
        self.set_y(-18)
        self.set_font("Arial", "", 7.5)
        self.set_text_color(140, 140, 140)
        self.cell(0, 5, "PYRESEC by NanoClone Systems Ltd.  |  Confidential - for the addressed recipient only", align="L")
        self.cell(0, 5, f"Page {self.page_no()}/{{nb}}", align="R")


def _setup_fonts(pdf: _ReportPDF) -> bool:
    for directory, families in _FONT_SETS:
        try:
            resolved = {}
            for family, styles in families.items():
                regular = styles.get("")
                for style, filename in styles.items():
                    path = os.path.join(directory, filename)
                    if not os.path.exists(path):
                        path = os.path.join(directory, regular) if regular else ""
                    if not path or not os.path.exists(path):
                        raise FileNotFoundError(f"{family}/{style} in {directory}")
                    resolved[(family, style)] = path
            for (family, style), path in resolved.items():
                pdf.add_font(family, style, path)
            return True
        except Exception:
            continue
    pdf.set_font("Helvetica")  # core-font fallback (fpdf2 auto-substitutes unknown families)
    return False


def _severity_counts(findings: list) -> dict:
    counts = {}
    for f in findings:
        sev = (f.get("severity") or "INFO").upper()
        counts[sev] = counts.get(sev, 0) + 1
    return counts


def _risk_rating(counts: dict) -> str:
    for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
        if counts.get(sev):
            return sev
    return "CLEAN"


def _section_title(pdf: _ReportPDF, num: str, title: str):
    pdf.ln(4)
    pdf.set_font("Arial", "B", 13)
    pdf.set_text_color(25, 25, 25)
    pdf.cell(0, 8, f"{num}. {title}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(176, 32, 48)
    pdf.set_line_width(0.6)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + 34, pdf.get_y())
    pdf.set_line_width(0.2)
    pdf.ln(5)


def _body(pdf: _ReportPDF, text: str, size: int = 10):
    pdf.set_font("Arial", "", size)
    pdf.set_text_color(45, 45, 45)
    pdf.multi_cell(0, 5.2, _sanitize(text), new_x="LMARGIN")
    pdf.ln(1)


def _code_block(pdf: _ReportPDF, code: str, label: str = ""):
    code = _sanitize(code)
    if len(code) > 3500:
        code = code[:3500] + "\n... [truncated]"
    pdf.ln(1)
    pdf.set_fill_color(244, 246, 248)
    pdf.set_draw_color(225, 228, 232)
    if label:
        pdf.set_font("Mono", "B", 8)
        pdf.set_text_color(90, 90, 90)
        pdf.cell(0, 5, f"  {label}", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Mono", "", 8)
    pdf.set_text_color(40, 40, 40)
    pdf.multi_cell(0, 4.2, code, border=1, fill=True, new_x="LMARGIN")
    pdf.ln(2)


def _finding_card(pdf: _ReportPDF, finding: dict, idx: int, category: str):
    sev = (finding.get("severity") or "INFO").upper()
    color = SEV_COLORS.get(sev, SEV_COLORS["INFO"])
    title = finding.get("type", "FINDING")
    cwe = finding.get("cwe") or finding.get("cve") or ""

    pdf.ln(1)
    y = pdf.get_y()
    if y > 255:
        pdf.add_page()

    pdf.set_fill_color(*color)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Arial", "B", 9.5)
    label = f"  {idx}. [{sev}] {title}"
    if cwe:
        label += f"   {cwe}"
    pdf.cell(0, 6.5, _sanitize(label), fill=True, new_x="LMARGIN", new_y="NEXT")

    pdf.set_text_color(45, 45, 45)
    pdf.set_font("Arial", "", 9)

    details = []
    if finding.get("line_number"):
        details.append(f"Line: {finding['line_number']}")
    if finding.get("package"):
        details.append(f"Package: {finding['package']} ({finding.get('affected_versions', '?')})")
    if finding.get("cve"):
        details.append(f"Advisory: {finding['cve']}")
    details.append(f"Category: {category}")
    pdf.set_font("Arial", "", 8.5)
    pdf.set_text_color(100, 100, 100)
    pdf.multi_cell(0, 4.5, _sanitize("  |  ".join(details)), new_x="LMARGIN")

    desc = finding.get("description")
    if desc:
        pdf.set_font("Arial", "", 9)
        pdf.set_text_color(45, 45, 45)
        pdf.multi_cell(0, 4.8, _sanitize(desc), new_x="LMARGIN")

    snippet = finding.get("line_content")
    if snippet:
        _code_block(pdf, f"  {snippet}", label="Evidence")


def generate_report(scan: dict, meta: Optional[dict] = None, out_dir: str = REPORT_DIR) -> str:
    """Generate a client-facing PDF from a PYRESEC scan response.

    scan: response dict from /v1/audit/quick-scan, /deep-repo, or /remediate
    meta: {"client": str, "repo_url": str, "engagement": str, "contact": str}
    Returns: path of the generated PDF.
    """
    meta = meta or {}
    client = _sanitize(meta.get("client", "client"))
    repo_url = _sanitize(meta.get("repo_url", ""))
    engagement = _sanitize(meta.get("engagement", "Security Assessment"))
    contact = _sanitize(meta.get("contact", ""))
    now = datetime.datetime.now(datetime.timezone.utc)
    ref = f"PYR-{now.strftime('%Y%m%d')}-{str(scan.get('file_hash', 'LOCAL'))[:6].upper()}"

    sast = scan.get("sast_findings") or []
    sca = scan.get("sca_findings") or []
    gas = scan.get("gas_findings") or []
    all_findings = sast + sca + gas
    counts = _severity_counts(all_findings)
    rating = _risk_rating(counts)

    os.makedirs(out_dir, exist_ok=True)
    safe_client = re.sub(r"[^A-Za-z0-9._-]", "_", client)[:40]
    out_path = os.path.join(out_dir, f"PYRESEC-{safe_client}-{now.strftime('%Y%m%d')}.pdf")

    pdf = _ReportPDF(ref, client)
    has_ttf = _setup_fonts(pdf)
    pdf.alias_nb_pages()

    # ---------- Cover ----------
    pdf.add_page()
    pdf.set_fill_color(20, 20, 24)
    pdf.rect(0, 0, 210, 105, style="F")

    pdf.set_y(30)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Arial", "B", 30)
    pdf.cell(0, 14, "PYRESEC", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Arial", "", 13)
    pdf.set_text_color(210, 210, 215)
    pdf.cell(0, 9, "Autonomous Security Assessment", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.set_y(120)
    pdf.set_text_color(25, 25, 25)
    pdf.set_font("Arial", "B", 20)
    pdf.multi_cell(0, 9, engagement, align="C", new_x="LMARGIN")
    pdf.ln(3)
    pdf.set_font("Arial", "", 12)
    pdf.set_text_color(70, 70, 70)
    pdf.cell(0, 8, f"Prepared for: {client}", align="C", new_x="LMARGIN", new_y="NEXT")
    if repo_url:
        pdf.set_text_color(60, 100, 170)
        pdf.cell(0, 7, repo_url, align="C", link=repo_url, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)

    # risk badge
    color = SEV_COLORS.get(rating, (90, 90, 90))
    pdf.set_fill_color(*color)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Arial", "B", 12)
    badge = f"  RISK RATING: {rating}  "
    bw = pdf.get_string_width(badge) + 6
    pdf.set_x((210 - bw) / 2)
    pdf.cell(bw, 9, badge, fill=True, new_x="LMARGIN", new_y="NEXT")

    pdf.ln(14)
    pdf.set_font("Arial", "", 9.5)
    pdf.set_text_color(110, 110, 110)
    pdf.cell(0, 6, f"Reference: {ref}    |    Issued: {now.strftime('%Y-%m-%d %H:%M UTC')}", align="C",
             new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, "Prepared by NanoClone Systems Ltd. - Automated analysis, human-approved delivery",
             align="C", new_x="LMARGIN", new_y="NEXT")

    # ---------- 1. Executive summary ----------
    pdf.add_page()
    _section_title(pdf, "1", "Executive Summary")
    total = len(all_findings)
    if total == 0:
        _body(pdf, "Automated analysis of the submitted codebase returned no actionable "
                   "security findings at the time of assessment. Continued monitoring is "
                   "recommended to catch regressions introduced by future changes.")
    else:
        parts = [f"{counts[s]} {s.lower()}" for s in SEV_ORDER if counts.get(s)]
        _body(pdf, f"Automated analysis identified {total} actionable finding(s): "
                   + ", ".join(parts) + ".")

    llm_text = scan.get("llm_analysis") or scan.get("llm_findings") or ""
    if llm_text:
        _body(pdf, _sanitize(llm_text).strip()[:2200])

    # summary table
    if total:
        pdf.ln(2)
        pdf.set_font("Arial", "B", 9.5)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(30, 7, "Severity", border=1, fill=False)
        pdf.cell(20, 7, "Count", border=1, align="C")
        pdf.cell(0, 7, "Meaning", border=1, new_x="LMARGIN", new_y="NEXT")
        meanings = {
            "CRITICAL": "Immediate exploitation risk - fix now",
            "HIGH": "Significant exposure - fix within days",
            "MEDIUM": "Real weakness - fix in current cycle",
            "LOW": "Hardening opportunity - schedule",
            "INFO": "Observation - review",
        }
        for sev in SEV_ORDER:
            if not counts.get(sev):
                continue
            c = SEV_COLORS[sev]
            pdf.set_fill_color(*c)
            pdf.set_text_color(255, 255, 255)
            pdf.set_font("Arial", "B", 9)
            pdf.cell(30, 6.5, sev, border=1, fill=True)
            pdf.set_text_color(40, 40, 40)
            pdf.set_font("Arial", "", 9)
            pdf.cell(20, 6.5, str(counts[sev]), border=1, align="C")
            pdf.cell(0, 6.5, _sanitize(meanings.get(sev, "")), border=1, new_x="LMARGIN", new_y="NEXT")

    # ---------- 2. Scope & methodology ----------
    pdf.ln(4)
    _section_title(pdf, "2", "Scope & Methodology")
    _body(pdf,
          "This assessment was produced by PYRESEC, an autonomous code-security engine "
          "combining pattern-based static analysis (SAST), dependency analysis (SCA), "
          "Solidity gas inspection, and large-language-model reasoning "
          f"(model: {scan.get('model', 'n/a')}). Findings were validated against the "
          "submitted source and are reported with reproducible line references.")
    if repo_url:
        _body(pdf, f"Target repository: {repo_url}")
    if scan.get("file_hash"):
        _body(pdf, f"Artifact fingerprint (SHA-family): {scan['file_hash']}")

    # ---------- 3. Findings ----------
    if total:
        pdf.ln(2)
        _section_title(pdf, "3", "Findings")
        idx = 1
        for f in sorted(sast, key=lambda x: SEV_ORDER.get(x.get("severity", "INFO"), 5)):
            _finding_card(pdf, f, idx, "SAST")
            idx += 1
        for f in sca:
            _finding_card(pdf, f, idx, "Dependency (SCA)")
            idx += 1
        for f in gas:
            _finding_card(pdf, f, idx, "Gas Optimization")
            idx += 1
    else:
        pdf.ln(2)
        _section_title(pdf, "3", "Findings")
        _body(pdf, "No findings.")

    # ---------- 4. Remediation ----------
    remediation = scan.get("remediation") if isinstance(scan.get("remediation"), dict) else None
    has_remediation = bool(scan.get("patched_code") or remediation or scan.get("changes_made"))
    if has_remediation:
        pdf.ln(2)
        _section_title(pdf, "4", "Remediation")
        changes = scan.get("changes_made") or (remediation or {}).get("changes_made") or []
        for ch in changes[:15]:
            _body(pdf, f"  -  {_sanitize(ch)}", size=9.5)
        notes = scan.get("security_notes") or (remediation or {}).get("security_notes") or []
        if notes:
            pdf.ln(1)
            _body(pdf, "Security notes:", size=9.5)
            for n in notes[:10]:
                _body(pdf, f"  -  {_sanitize(n)}", size=9.5)
        patched = scan.get("patched_code") or (remediation or {}).get("patched_code")
        if patched:
            _code_block(pdf, patched, label="Patched code (excerpt)")

    # ---------- N. Recommended next steps ----------
    sec_num = "5" if has_remediation else "4"
    pdf.ln(2)
    _section_title(pdf, sec_num, "Recommended Next Steps")
    upsell = meta.get("upsell")
    if upsell:
        _body(pdf, _sanitize(upsell))
    stripe_link = os.getenv("STRIPE_LINK_RETAINER", "")
    pdf.set_fill_color(240, 246, 255)
    pdf.set_draw_color(120, 150, 210)
    pdf.set_font("Arial", "B", 10.5)
    pdf.set_text_color(35, 60, 120)
    pdf.multi_cell(0, 6.5,
                   "  Continuous Monitoring: weekly re-scans, dependency CVE watch, and "
                   "regression alerts for this repository.",
                   border=1, fill=True, new_x="LMARGIN")
    pdf.set_font("Arial", "", 9.5)
    pdf.set_text_color(60, 60, 60)
    if stripe_link:
        pdf.multi_cell(0, 6, f"  Activate: {stripe_link}", link=stripe_link, new_x="LMARGIN")
    else:
        pdf.multi_cell(0, 6, "  Activate by replying to your assessment email.", new_x="LMARGIN")
    pdf.ln(2)

    if contact:
        pdf.set_font("Arial", "", 9)
        pdf.set_text_color(100, 100, 100)
        pdf.multi_cell(0, 5, _sanitize(f"Contact: {contact}"), new_x="LMARGIN")

    # ---------- Verification block ----------
    pdf.ln(3)
    pdf.set_fill_color(246, 246, 246)
    pdf.set_draw_color(220, 220, 220)
    pdf.set_font("Mono", "", 8)
    pdf.set_text_color(90, 90, 90)
    lines = [
        f"reference : {ref}",
        f"issued    : {now.strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"engine    : PYRESEC ({scan.get('agent', 'n/a')})",
        f"model     : {scan.get('model', 'n/a')}",
        f"hash      : {scan.get('file_hash', 'n/a')}",
        f"findings  : {total} ({rating})",
    ]
    pdf.multi_cell(0, 4.4, "\n".join(lines), border=1, fill=True, new_x="LMARGIN")

    if not has_ttf:
        pass  # Helvetica fallback already applied

    pdf.output(out_path)
    return out_path


if __name__ == "__main__":
    sample_scan = {
        "status": "success",
        "tier": "Deep Audit",
        "agent": "0x17eA81BF3bD47Fb6524a09a52DBB77fe1f4ab687",
        "file_hash": "ab12cd34ef56",
        "sast_findings": [
            {"type": "COMMAND_INJECTION", "severity": "CRITICAL", "cwe": "CWE-78",
             "description": "User-controlled input reaches os.system() without sanitization, "
                            "allowing arbitrary command execution.",
             "line_number": 42, "line_content": "os.system('git clone ' + user_url)"},
            {"type": "HARDCODED_SECRET", "severity": "CRITICAL", "cwe": "CWE-798",
             "description": "Hardcoded API key found in source.",
             "line_number": 7, "line_content": "API_KEY = 'sk-live-xxxx'"},
            {"type": "XSS", "severity": "HIGH", "cwe": "CWE-79",
             "description": "Unescaped user input written to innerHTML.",
             "line_number": 88, "line_content": "el.innerHTML = query;"},
        ],
        "sca_findings": [
            {"type": "SCA_VULN", "severity": "HIGH", "cwe": "CWE-1395",
             "package": "requests", "cve": "CVE-2024-35195", "affected_versions": "<2.32.0"},
        ],
        "gas_findings": [
            {"type": "GAS_STORAGE_IN_LOOP", "severity": "MEDIUM",
             "description": "Storage writes inside loops are expensive.",
             "line_number": 113, "line_content": "for (...) { storage[i] = x; }"},
        ],
        "llm_analysis": "The codebase mixes unsanitized shell input with secrets committed "
                        "in source. Highest risk is the command-injection path reachable "
                        "from an internet-facing handler.",
        "total_findings": 5,
        "model": "qwen/qwen3.8-27b",
        "changes_made": [
            "Replaced os.system with subprocess.run and an allow-list of destinations.",
            "Moved API key to environment variable.",
        ],
        "security_notes": [
            "Validate URLs against an allow-list before any network call.",
            "Rotate the exposed key; treat it as compromised.",
        ],
        "patched_code": "import subprocess\n\ndef clone(url):\n    if not url.startswith(ALLOWED_PREFIX):\n        raise ValueError('blocked')\n    subprocess.run(['git', 'clone', url], check=True)\n",
        "total_vulnerabilities": 5,
    }
    sample_meta = {
        "client": "acme-dao",
        "repo_url": "https://github.com/acme-dao/contracts",
        "engagement": "Security Assessment & Remediation",
        "contact": "security@nanoclonesystems.com",
        "upsell": "Given the critical findings above, we recommend activating continuous "
                  "monitoring before shipping further changes.",
    }
    path = generate_report(sample_scan, sample_meta)
    print(f"OK: {path} ({os.path.getsize(path)} bytes)")
