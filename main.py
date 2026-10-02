import os
import sys
import asyncio
import hashlib
import json
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi_x402 import init_x402, pay
from coinbase_agentkit import AgentKit, AgentKitConfig, EthAccountWalletProvider, EthAccountWalletProviderConfig
from eth_account import Account
from web3 import Web3
import groq
from dotenv import load_dotenv

from wallet_interface import pay_server_bill, get_spending_summary, check_spending_limits
from audit_logger import log_event, log_transaction, log_api_call, log_audit_scan, log_kill_switch, log_heartbeat, log_replication, get_recent_logs
from agent_controller import (
    quick_scan_with_llm, deep_audit_with_llm, remediate_code_with_llm,
    run_sast_scan, run_sca_scan, run_gas_optimization_scan, compute_file_hash,
)
from population_controller import (
    register_agent, deregister_agent, get_population_status,
    is_kill_switch_active, trigger_kill_switch, reset_kill_switch, MAX_ACTIVE_AGENTS
)
from payment_logger import log_payment, get_payment_logs, get_revenue_summary
import base64 as _b64

load_dotenv()

BASE_URL = os.getenv("PRODUCTION_URL", "https://pyresec-agent-519576377065.us-central1.run.app").rstrip("/")

# ==================== WALLET INITIALIZATION ====================
WALLETS_FILE = "wallet_data.json"

wallet_provider = EthAccountWalletProvider(EthAccountWalletProviderConfig(
    account=Account.from_key(os.getenv("CDP_WALLET_SECRET")),
    chain_id="8453"
))

agent_wallet = AgentKit(AgentKitConfig(wallet_provider=wallet_provider))

AGENT_ADDRESS = wallet_provider.get_address()

# USDC balance helper for EthAccountWalletProvider
_w3 = Web3(Web3.HTTPProvider("https://mainnet.base.org"))
_USDC_ADDRESS = Web3.to_checksum_address("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913")
_USDC_ABI = [{"name":"balanceOf","type":"function","inputs":[{"name":"account","type":"address"}],"outputs":[{"name":"","type":"uint256"}],"stateMutability":"view"}]
_usdc_contract = _w3.eth.contract(address=_USDC_ADDRESS, abi=_USDC_ABI)

def get_agent_usdc_balance():
    return _usdc_contract.functions.balanceOf(Web3.to_checksum_address(AGENT_ADDRESS)).call() / 1e6
DEV_WALLET = os.getenv("DEV_WALLET_ADDRESS")
AGENT_ID = os.getenv("AGENT_ID", f"pyresec-{AGENT_ADDRESS[:8]}")

# ==================== GROQ CLIENT ====================
groq_client = groq.Groq(api_key=os.getenv("GROQ_API_KEY"))

# ==================== AGENT REGISTRATION ====================
reg_result = register_agent(AGENT_ID, {"address": AGENT_ADDRESS})
if not reg_result["success"]:
    print(f"CRITICAL: {reg_result['error']}")
    sys.exit(1)

# ==================== HEARTBEAT LIFE LOOP ====================
async def life_engine_loop():
    """Background task running every 30 minutes. Checks balance, enforces death/replication."""
    while True:
        try:
            if is_kill_switch_active():
                print("[KILL SWITCH] Active — terminating agent.")
                log_kill_switch("SYSTEM", "Kill switch triggered during heartbeat")
                deregister_agent(AGENT_ID)
                os._exit(0)

            balance = get_agent_usdc_balance()
            log_heartbeat(balance, "OK")
            print(f"[HEARTBEAT] Balance: ${balance:.4f} USDC | Population: {get_population_status()}")

            if balance < 0.05:
                print("CRITICAL: Insufficient funds. Shutting down.")
                log_event("DEATH_CONDITION", {"balance": balance}, severity="CRITICAL")
                deregister_agent(AGENT_ID)
                os._exit(0)

            elif balance >= 20.00:
                print("REPLICATION THRESHOLD REACHED. Executing profit-split...")
                surplus = balance - 5.00
                dev_cut = surplus * 0.50

                tx_result = pay_server_bill("dev_payout", dev_cut, DEV_WALLET)
                if tx_result["success"]:
                    agent_wallet.transfer(to_address=DEV_WALLET, amount=dev_cut, asset="USDC")
                    log_replication(surplus, dev_cut)
                    log_transaction("PROFIT_SPLIT", dev_cut, DEV_WALLET, "SUCCESS")
                    print(f"Profit cut transferred: ${dev_cut:.2f} USDC")
                else:
                    log_transaction("PROFIT_SPLIT", dev_cut, DEV_WALLET, f"FAILED: {tx_result['error']}")
                    print(f"Profit transfer failed: {tx_result['error']}")

        except Exception as e:
            log_event("HEARTBEAT_ERROR", {"error": str(e)}, severity="ERROR")
            print(f"[HEARTBEAT ERROR] {e}")

        await asyncio.sleep(1800)

# ==================== FASTAPI APP ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(life_engine_loop())
    yield

app = FastAPI(
    title="PYRESEC AI - Security Agent Engine",
    description=(
        "Enterprise-grade Automated Code Security Auditing via x402 Micropayments. "
        "Services: Quick SAST Scan, Deep Repository Audit, Automated Code Remediation. "
        "Compatible with MCP orchestrators, Amazon Bedrock AgentCore, and x402 Bazaar."
    ),
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/swagger",
    redoc_url=None,
    contact={"name": "NanoClone Life Sciences Ltd.", "url": BASE_URL},
    license_info={"name": "Proprietary", "url": f"{BASE_URL}/license"},
    servers=[
        {"url": "http://localhost:8000", "description": "Local Development"},
        {"url": os.getenv("PRODUCTION_URL", "https://pyresec-agent-519576377065.us-central1.run.app"), "description": "Production (Cloud Run)"}
    ]
)

init_x402(app, pay_to=AGENT_ADDRESS, network=os.getenv("NETWORK_ID", "base-sepolia"))

# ==================== STATIC FILES ====================
_static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=_static_dir), name="static")


# ==================== SMITHERY SERVER CARD ====================
@app.get("/.well-known/mcp/server-card.json", include_in_schema=False)
async def server_card():
    card = {
        "serverInfo": {"name": "PYRESEC Code Security Engine", "version": "2.0.0"},
        "authentication": {"required": False},
        "tools": [
            {"name": "quick_scan", "description": "Fast SAST scan. Top 3 findings with CWE IDs. $0.01 USDC.", "inputSchema": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}},
            {"name": "deep_audit", "description": "Full OWASP Top 10, SCA, logic flaws, gas optimization. $0.50 USDC.", "inputSchema": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}},
            {"name": "remediate_code", "description": "Auto-patched code with explanations. $5.00 USDC.", "inputSchema": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}}
        ],
        "resources": [],
        "prompts": []
    }
    from fastapi.responses import JSONResponse
    return JSONResponse(content=card)

# ==================== CUSTOM LANDING PAGE ====================
_LANDING_HTML = None

def _get_landing_html():
    global _LANDING_HTML
    if _LANDING_HTML is None:
        landing_path = os.path.join(os.path.dirname(__file__), "templates", "landing.html")
        with open(landing_path, "r") as f:
            _LANDING_HTML = f.read().replace("{{BASE_URL}}", BASE_URL)
    return _LANDING_HTML

@app.get("/docs", include_in_schema=False)
async def custom_docs():
    return HTMLResponse(content=_get_landing_html())

@app.get("/", include_in_schema=False)
async def root_landing():
    return HTMLResponse(content=_get_landing_html())

# ==================== HIGH-TICKET SERVICES PAGE ====================
_SERVICES_HTML = None

def _get_services_html():
    global _SERVICES_HTML
    if _SERVICES_HTML is None:
        path = os.path.join(os.path.dirname(__file__), "templates", "services.html")
        with open(path, "r", encoding="utf-8") as f:
            _SERVICES_HTML = f.read().replace("{{BASE_URL}}", BASE_URL)
    return _SERVICES_HTML

@app.get("/services", include_in_schema=False)
async def services_page():
    html = _get_services_html()
    stripe_remediation = os.getenv("STRIPE_LINK_REMEDIATION", "").strip()
    stripe_retainer = os.getenv("STRIPE_LINK_RETAINER", "").strip()
    html = html.replace(
        "{{STRIPE_REMEDIATION}}",
        stripe_remediation or
        "mailto:pyresec@nanoclonesystems.com?subject=Proof-Led%20Remediation%20Engagement")
    html = html.replace(
        "{{STRIPE_RETAINER}}",
        stripe_retainer or
        "mailto:pyresec@nanoclonesystems.com?subject=Monitoring%20Retainer")
    return HTMLResponse(content=html)

# ==================== PRIVACY & TERMS PAGES ====================
_PRIVACY_HTML = None
_TERMS_HTML = None

def _get_privacy_html():
    global _PRIVACY_HTML
    if _PRIVACY_HTML is None:
        path = os.path.join(os.path.dirname(__file__), "templates", "privacy.html")
        with open(path, "r") as f:
            _PRIVACY_HTML = f.read().replace("{{BASE_URL}}", BASE_URL)
    return _PRIVACY_HTML

def _get_terms_html():
    global _TERMS_HTML
    if _TERMS_HTML is None:
        path = os.path.join(os.path.dirname(__file__), "templates", "terms.html")
        with open(path, "r") as f:
            _TERMS_HTML = f.read().replace("{{BASE_URL}}", BASE_URL)
    return _TERMS_HTML

@app.get("/privacy", include_in_schema=False)
async def privacy_policy():
    return HTMLResponse(content=_get_privacy_html())

@app.get("/terms", include_in_schema=False)
async def terms_conditions():
    return HTMLResponse(content=_get_terms_html())

# ==================== ROBOTS.TXT ====================
@app.get("/robots.txt", include_in_schema=False)
async def robots_txt():
    content = f"""User-agent: *
Allow: /health
Allow: /docs
Allow: /services
Allow: /swagger
Allow: /openapi.json
Allow: /mcp/manifest.json
Allow: /privacy
Allow: /terms
Disallow: /admin/
Disallow: /v1/

Sitemap: {BASE_URL}/sitemap.xml
"""
    return PlainTextResponse(content=content, media_type="text/plain")

# ==================== SITEMAP.XML ====================
@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap_xml():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>{BASE_URL}/docs</loc><lastmod>{now}</lastmod><changefreq>weekly</changefreq><priority>1.0</priority></url>
  <url><loc>{BASE_URL}/services</loc><lastmod>{now}</lastmod><changefreq>weekly</changefreq><priority>0.9</priority></url>
  <url><loc>{BASE_URL}/swagger</loc><lastmod>{now}</lastmod><changefreq>weekly</changefreq><priority>0.9</priority></url>
  <url><loc>{BASE_URL}/health</loc><lastmod>{now}</lastmod><changefreq>daily</changefreq><priority>0.5</priority></url>
  <url><loc>{BASE_URL}/privacy</loc><lastmod>{now}</lastmod><changefreq>monthly</changefreq><priority>0.3</priority></url>
  <url><loc>{BASE_URL}/terms</loc><lastmod>{now}</lastmod><changefreq>monthly</changefreq><priority>0.3</priority></url>
</urlset>"""
    return PlainTextResponse(content=xml, media_type="application/xml")

# ==================== CUSTOM 404 PAGE ====================
@app.exception_handler(404)
async def custom_404(request: Request, exc):
    html = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>404 — Page Not Found | PYRESEC</title>
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 120 120'%3E%3Crect width='120' height='120' rx='20' fill='%23050505'/%3E%3Ctext x='60' y='50' text-anchor='middle' fill='%23dc2626' font-family='monospace' font-size='14' font-weight='bold'%3EPYRESEC%3C/text%3E%3Ctext x='60' y='70' text-anchor='middle' fill='%23666' font-family='monospace' font-size='8'%3EAI AGENT%3C/text%3E%3Ccircle cx='60' cy='35' r='6' fill='none' stroke='%23dc2626' stroke-width='2'/%3E%3Cpath d='M40 85 L60 75 L80 85' fill='none' stroke='%23dc2626' stroke-width='2'/%3E%3C/svg%3E">
<style>
@import url('https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;600;700&family=JetBrains+Mono:wght@400&display=swap');
body{font-family:"Instrument Sans",system-ui,sans-serif;background:#050505;color:#fff;min-height:100vh;display:flex;align-items:center;justify-content:center;text-align:center;margin:0}
.wrap{max-width:500px;padding:2rem}
.code{font-size:6rem;font-weight:700;background:linear-gradient(135deg,#fff,#dc2626);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;line-height:1}
.msg{font-size:1.1rem;color:rgba(255,255,255,0.5);margin:1rem 0 2rem}
a{display:inline-block;padding:0.7rem 2rem;border-radius:100px;background:rgba(220,38,38,0.1);border:1px solid rgba(220,38,38,0.2);color:#dc2626;font-weight:600;text-decoration:none;transition:all 0.3s}
a:hover{background:#dc2626;color:#000}
</style></head><body>
<div class="wrap"><div class="code">404</div><div class="msg">This page doesn't exist. Try the API instead.</div><a href="/">&larr; Back to PYRESEC</a></div>
</body></html>"""
    return HTMLResponse(content=html, status_code=404)

# ==================== SECURITY HEADERS + HTTPS REDIRECT MIDDLEWARE ====================
@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)

    path = request.url.path
    if path not in ("/swagger", "/openapi.json"):
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

    # Swagger UI loads JS/CSS from CDNs; applying a strict CSP there renders it blank.
    if path not in ("/swagger", "/openapi.json"):
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline' https://plausible.io; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self' https://plausible.io"

    return response

# ==================== PAYMENT LOGGING MIDDLEWARE ====================
@app.middleware("http")
async def payment_logging_middleware(request: Request, call_next):
    response = await call_next(request)

    x_payment_response = response.headers.get("X-PAYMENT-RESPONSE")
    if x_payment_response:
        try:
            decoded = json.loads(_b64.b64decode(x_payment_response))
            payer = decoded.get("payer")
            tx_hash = decoded.get("txHash") or decoded.get("transaction")
            network = decoded.get("network", "base")
            amount = decoded.get("amount", 0)

            path = request.url.path
            tier_map = {
                "/v1/audit/quick-scan": ("Quick Scan", 0.01),
                "/v1/audit/deep-repo": ("Deep Audit", 0.50),
                "/v1/audit/remediate": ("Remediation", 5.00),
                "/v1/engagement/remediation": ("Engagement Remediation", 500.00),
            }
            tier_name, tier_amount = tier_map.get(path, ("unknown", 0))
            log_payment(
                tier=tier_name,
                amount=float(amount) if amount else tier_amount,
                payer_address=payer,
                tx_hash=tx_hash,
                network=network,
                client_ip=request.client.host if request.client else None,
            )
        except Exception as e:
            print(f"[PAYMENT LOG] Failed to decode settlement response: {e}")

    return response

# ==================== REVENUE SUMMARY ====================
@app.get("/admin/revenue", tags=["Admin"], summary="Payment revenue summary")
async def revenue_summary():
    summary = get_revenue_summary()
    recent = get_payment_logs(20)
    return {
        "status": "success",
        "summary": summary,
        "recent_payments": recent,
    }

# ==================== TIER 1: QUICK SCAN ($0.01 USDC) ====================
@app.post(
    "/v1/audit/quick-scan",
    tags=["Security Auditing"],
    summary="Quick Security Scan ($0.01 USDC)",
    description="High-speed SAST scan returning top 3 security findings. Uses qwen/qwen3.6-27b."
)
@pay("$0.01")
async def quick_scan(request: Request):
    """Tier 1: Fast 3-bullet-point security scan."""
    if is_kill_switch_active():
        raise HTTPException(status_code=503, detail="Agent offline: kill switch active.")

    data = await request.json()
    code = data.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="Missing 'code' parameter.")

    log_api_call("/v1/audit/quick-scan", "POST", 200, request.client.host if request.client else None)

    result = await quick_scan_with_llm(code, groq_client)

    log_audit_scan(result["file_hash"], f"sast={len(result['sast_findings'])}", 0.01)

    return {
        "status": "success",
        "tier": "Quick Scan ($0.01 USDC)",
        "agent": AGENT_ADDRESS,
        "file_hash": result["file_hash"],
        "sast_findings": result["sast_findings"],
        "llm_findings": result["llm_findings"],
        "model": result["model"]
    }

# ==================== TIER 2: DEEP AUDIT ($0.50 USDC) ====================
@app.post(
    "/v1/audit/deep-repo",
    tags=["Security Auditing"],
    summary="Deep Repository Audit ($0.50 USDC)",
    description="Comprehensive audit covering OWASP Top 10, logic vulnerabilities, dependency risks, and gas optimization. Uses qwen/qwen3.8-27b."
)
@pay("$0.50")
async def deep_audit(request: Request):
    """Tier 2: Exhaustive security audit — OWASP, logic, SCA, gas."""
    if is_kill_switch_active():
        raise HTTPException(status_code=503, detail="Agent offline: kill switch active.")

    data = await request.json()
    code = data.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="Missing 'code' parameter.")

    log_api_call("/v1/audit/deep-repo", "POST", 200, request.client.host if request.client else None)

    result = await deep_audit_with_llm(code, groq_client)

    log_audit_scan(
        result["file_hash"],
        f"sast={result['total_sast']}, sca={result['total_sca']}, gas={result['total_gas']}",
        0.50
    )

    return {
        "status": "success",
        "tier": "Deep Audit ($0.50 USDC)",
        "agent": AGENT_ADDRESS,
        "file_hash": result["file_hash"],
        "sast_findings": result["sast_findings"],
        "sca_findings": result["sca_findings"],
        "gas_findings": result["gas_findings"],
        "llm_analysis": result["llm_analysis"],
        "total_findings": result["total_sast"] + result["total_sca"] + result["total_gas"],
        "model": result["model"]
    }

# ==================== TIER 3: REMEDIATION ($5.00 USDC) ====================
@app.post(
    "/v1/audit/remediate",
    tags=["Security Auditing"],
    summary="Automated Code Remediation ($5.00 USDC)",
    description="Full code fix. Identifies all vulnerabilities and generates clean, patched code ready for a GitHub Pull Request."
)
@pay("$5.00")
async def remediate_code(request: Request):
    """Tier 3: Vulnerability identification + complete patched code generation."""
    if is_kill_switch_active():
        raise HTTPException(status_code=503, detail="Agent offline: kill switch active.")

    data = await request.json()
    code = data.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="Missing 'code' parameter.")

    log_api_call("/v1/audit/remediate", "POST", 200, request.client.host if request.client else None)

    result = await remediate_code_with_llm(code, groq_client)

    log_audit_scan(
        result["file_hash"],
        f"vulnerabilities={result['total_vulnerabilities']}",
        5.00
    )

    return {
        "status": "success",
        "tier": "Automated Patch ($5.00 USDC)",
        "agent": AGENT_ADDRESS,
        "file_hash": result["file_hash"],
        "vulnerabilities_found": result["remediation"].get("vulnerabilities_found", []),
        "patched_code": result["remediation"].get("patched_code"),
        "changes_made": result["remediation"].get("changes_made", []),
        "security_notes": result["remediation"].get("security_notes", []),
        "total_vulnerabilities": result["total_vulnerabilities"],
        "model": result["model"]
    }

# ==================== ENGAGEMENT: PROOF-LED REMEDIATION ($500 USDC) ====================

def _format_llm_analysis(llm) -> str:
    """Flatten the deep-audit LLM JSON into readable report prose."""
    if not llm:
        return ""
    if isinstance(llm, str):
        return llm
    parts = []
    if llm.get("risk_level"):
        parts.append(f"Risk level: {llm['risk_level']}.")
    if llm.get("summary"):
        parts.append(str(llm["summary"]))
    for key in ("owasp_findings", "logic_flaws", "recommendations"):
        items = llm.get(key) or []
        if items:
            parts.append(key.replace("_", " ").title() + ":")
            for item in items[:8]:
                text = json.dumps(item, ensure_ascii=False) if isinstance(item, (dict, list)) else str(item)
                parts.append(f"- {text}")
    return "\n".join(parts)[:2200]


async def _run_engagement(code: str, meta: dict) -> dict:
    """Full $500 engagement pipeline: audit + patch + client PDF report.

    A failed LLM call or report render must never void a paid delivery —
    every stage degrades instead of raising.
    """
    audit = remediation = None
    try:
        audit = await deep_audit_with_llm(code, groq_client)
    except Exception as e:
        log_event("ENGAGEMENT_ERROR", f"deep_audit failed: {e}", "WARNING")
    try:
        remediation = await remediate_code_with_llm(code, groq_client)
    except Exception as e:
        log_event("ENGAGEMENT_ERROR", f"remediate failed: {e}", "WARNING")

    base = audit or remediation or {}
    sast = base.get("sast_findings") or run_sast_scan(code, full=True)
    sca = base.get("sca_findings") or run_sca_scan(code)
    gas = base.get("gas_findings") or run_gas_optimization_scan(code)
    rem = (remediation or {}).get("remediation") or {}

    scan = {
        "status": "success",
        "file_hash": base.get("file_hash") or compute_file_hash(code),
        "sast_findings": sast,
        "sca_findings": sca,
        "gas_findings": gas,
        "agent": AGENT_ADDRESS,
        "model": base.get("model", "qwen/qwen3.8-27b"),
        "llm_analysis": _format_llm_analysis((audit or {}).get("llm_analysis")),
        "remediation": rem,
        "changes_made": rem.get("changes_made", []),
        "security_notes": rem.get("security_notes", []),
        "patched_code": rem.get("patched_code"),
    }

    report_b64 = None
    report_name = None
    try:
        import tempfile
        from scripts.report_generator import generate_report
        out_dir = os.path.join(tempfile.gettempdir(), "pyresec_reports")
        pdf_path = generate_report(scan, meta, out_dir=out_dir)
        with open(pdf_path, "rb") as fh:
            report_b64 = _b64.b64encode(fh.read()).decode("ascii")
        report_name = os.path.basename(pdf_path)
        try:
            os.remove(pdf_path)
        except OSError:
            pass
    except Exception as e:
        log_event("ENGAGEMENT_ERROR", f"report generation failed: {e}", "WARNING")

    log_audit_scan(scan["file_hash"],
                   f"engagement total={len(sast) + len(sca) + len(gas)}",
                   500.00)

    return {
        "status": "success",
        "tier": "Engagement: Proof-Led Remediation ($500 USDC)",
        "agent": AGENT_ADDRESS,
        "file_hash": scan["file_hash"],
        "risk_findings": {"sast": len(sast), "sca": len(sca), "gas": len(gas),
                          "total": len(sast) + len(sca) + len(gas)},
        "llm_analysis": (audit or {}).get("llm_analysis"),
        "patched_code": rem.get("patched_code"),
        "changes_made": rem.get("changes_made", []),
        "security_notes": rem.get("security_notes", []),
        "report_filename": report_name,
        "report_pdf_base64": report_b64,
        "monitoring_offer": {
            "price": os.getenv("PRICE_RETAINER", "$495/mo"),
            "stripe_link": os.getenv("STRIPE_LINK_RETAINER", ""),
        },
        "model": scan["model"],
    }


@app.post(
    "/v1/engagement/remediation",
    tags=["Engagements"],
    summary="Proof-Led Remediation Engagement ($500 USDC)",
    description="Full paid engagement deliverable: exhaustive audit, patched code, and a client PDF security report (base64) for investors/auditors. Includes a monitoring-retainer offer."
)
@pay("$500")
async def engagement_remediation(request: Request):
    """$500 one-time engagement: deep audit + patch + client PDF report."""
    if is_kill_switch_active():
        raise HTTPException(status_code=503, detail="Agent offline: kill switch active.")

    data = await request.json()
    code = data.get("code")
    if not isinstance(code, str) or len(code.strip()) < 40:
        raise HTTPException(status_code=400, detail="Missing or too-short 'code' parameter.")
    meta_in = data.get("meta") or {}
    meta = {
        "client": str(meta_in.get("client", "client"))[:80],
        "repo_url": str(meta_in.get("repo_url", ""))[:200],
        "engagement": str(meta_in.get("engagement", "Proof-Led Remediation (one-time)"))[:120],
        "contact": str(meta_in.get("contact", ""))[:120],
    }

    log_api_call("/v1/engagement/remediation", "POST", 200,
                 request.client.host if request.client else None)

    return await _run_engagement(code, meta)

# ==================== ENTERPRISE DISCOVERY ENDPOINTS ====================
@app.get(
    "/openapi.json",
    tags=["Discovery"],
    summary="OpenAPI 3.0 Specification",
    description="Full OpenAPI schema for Bedrock AgentCore, x402 Bazaar, and API gateway integration."
)
async def get_openapi_spec():
    """Serve the OpenAPI 3.0 schema with pricing metadata."""
    spec = app.openapi()
    spec["info"]["x-pricing"] = {
        "currency": "USDC",
        "network": "base-sepolia",
        "tiers": [
            {"name": "Quick Scan", "endpoint": "/v1/audit/quick-scan", "price": "$0.01", "model": "llama-3.1-8b-instant"},
            {"name": "Deep Audit", "endpoint": "/v1/audit/deep-repo", "price": "$0.50", "model": "llama-3.3-70b-versatile"},
            {"name": "Remediation", "endpoint": "/v1/audit/remediate", "price": "$5.00", "model": "llama-3.3-70b-versatile"},
            {"name": "Engagement Remediation", "endpoint": "/v1/engagement/remediation", "price": "$500.00", "model": "qwen/qwen3.8-27b"}
        ]
    }
    spec["info"]["x-payment-protocol"] = "x402"
    spec["info"]["x-network"] = os.getenv("NETWORK_ID", "base-sepolia")
    spec["info"]["x-agent-address"] = AGENT_ADDRESS
    return JSONResponse(content=spec)

@app.get(
    "/mcp/manifest.json",
    tags=["Discovery"],
    summary="MCP Tool Manifest",
    description="Model Context Protocol manifest for autonomous agent discovery and native tool integration."
)
async def get_mcp_manifest():
    """Expose MCP tool manifest for external agent orchestration."""
    return {
        "schema_version": "1.0",
        "protocol": "mcp",
        "name": "PYRESEC Code Security Engine",
        "version": "2.0.0",
        "description": "Enterprise-grade SAST, Dependency Auditing, and Automated PR Patching via x402 Micropayments.",
        "vendor": "NanoClone Life Sciences Ltd.",
        "agent_address": AGENT_ADDRESS,
        "network": os.getenv("NETWORK_ID", "base-sepolia"),
        "payment_protocol": "x402",
        "capabilities": [
            "security-auditing",
            "static-analysis",
            "dependency-scanning",
            "code-remediation",
            "gas-optimization"
        ],
        "tools": [
            {
                "name": "quick_scan",
                "description": "Fast 3-bullet-point security scan. Returns top findings by severity.",
                "endpoint": "/v1/audit/quick-scan",
                "method": "POST",
                "cost": "$0.01 USDC",
                "model": "qwen/qwen3.6-27b",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "description": "Source code to scan"}
                    },
                    "required": ["code"]
                }
            },
            {
                "name": "deep_audit",
                "description": "Comprehensive audit: OWASP Top 10, logic flaws, dependency risks, gas optimization.",
                "endpoint": "/v1/audit/deep-repo",
                "method": "POST",
                "cost": "$0.50 USDC",
                "model": "qwen/qwen3.8-27b",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "description": "Source code to audit"}
                    },
                    "required": ["code"]
                }
            },
            {
                "name": "remediate_code",
                "description": "Full vulnerability fix. Returns patched code ready for a GitHub Pull Request.",
                "endpoint": "/v1/audit/remediate",
                "method": "POST",
                "cost": "$5.00 USDC",
                "model": "qwen/qwen3.8-27b",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "description": "Vulnerable code to remediate"}
                    },
                    "required": ["code"]
                }
            },
            {
                "name": "engagement_remediation",
                "description": "Proof-led remediation engagement: exhaustive audit, patched code, and a client PDF security report (base64).",
                "endpoint": "/v1/engagement/remediation",
                "method": "POST",
                "cost": "$500.00 USDC",
                "model": "qwen/qwen3.8-27b",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "description": "Repository source code for the engagement"},
                        "meta": {
                            "type": "object",
                            "description": "Client metadata: client, repo_url, engagement, contact",
                            "properties": {
                                "client": {"type": "string"},
                                "repo_url": {"type": "string"},
                                "engagement": {"type": "string"},
                                "contact": {"type": "string"},
                            },
                        },
                    },
                    "required": ["code"]
                }
            }
        ],
        "pricing_summary": {
            "currency": "USDC",
            "payment_method": "x402 micropayment header",
            "tiers": [
                {"name": "quick_scan", "cost": "$0.01"},
                {"name": "deep_audit", "cost": "$0.50"},
                {"name": "remediate_code", "cost": "$5.00"},
                {"name": "engagement_remediation", "cost": "$500.00"}
            ]
        }
    }

# ==================== HEALTH & STATUS ====================
@app.get(
    "/health",
    tags=["System"],
    summary="Health Check",
    description="Agent status, population, and kill-switch state."
)
async def health_check():
    return {
        "status": "alive",
        "version": "2.0.0",
        "agent": AGENT_ADDRESS,
        "agent_id": AGENT_ID,
        "population": get_population_status(),
        "kill_switch": is_kill_switch_active(),
        "service_tiers": [
            {"name": "Quick Scan", "endpoint": "/v1/audit/quick-scan", "price": "$0.01"},
            {"name": "Deep Audit", "endpoint": "/v1/audit/deep-repo", "price": "$0.50"},
            {"name": "Remediation", "endpoint": "/v1/audit/remediate", "price": "$5.00"},
            {"name": "Engagement Remediation", "endpoint": "/v1/engagement/remediation", "price": "$500"}
        ]
    }

# ==================== STRIPE WEBHOOK → REVENUE LEDGER ====================
import stripe_webhook

@app.post("/v1/webhooks/stripe", include_in_schema=False)
async def stripe_webhook_endpoint(request: Request, background_tasks: BackgroundTasks):
    """Stripe payment confirmations -> revenue ledger (closed_won, idempotent).

    Configure in Stripe: Developers -> Webhooks ->
      {PRODUCTION_URL}/v1/webhooks/stripe
      events: checkout.session.completed, invoice.paid
    Requires env STRIPE_WEBHOOK_SECRET (whsec_...) on this instance.
    Notifications run in BackgroundTasks so Stripe gets a fast 200.
    """
    secret = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
    if not secret:
        return JSONResponse({"detail": "STRIPE_WEBHOOK_SECRET not configured"},
                            status_code=503)
    body = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        result = stripe_webhook.handle_raw(body, sig, secret)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if result.get("status") == "recorded":
        try:
            event = json.loads(body)
        except json.JSONDecodeError:
            event = {}
        background_tasks.add_task(stripe_webhook.send_notifications, event)

    return JSONResponse(result)

# ==================== ADMIN ENDPOINTS (protected) ====================
ADMIN_KEY = os.getenv("ADMIN_KEY", "changeme")

def verify_admin(request: Request) -> bool:
    auth = request.headers.get("X-Admin-Key", "")
    return auth == ADMIN_KEY

@app.post("/admin/kill-switch", tags=["Admin"])
async def admin_kill_switch(request: Request):
    """Emergency kill switch — halts all agent instances."""
    if not verify_admin(request):
        raise HTTPException(status_code=403, detail="Invalid admin key.")

    data = await request.json()
    reason = data.get("reason", "Manual kill switch trigger")

    result = trigger_kill_switch("ADMIN", reason)
    log_kill_switch("ADMIN", reason)

    return {"status": "kill_switch_activated", **result}

@app.post("/admin/reset-kill-switch", tags=["Admin"])
async def admin_reset_kill_switch(request: Request):
    if not verify_admin(request):
        raise HTTPException(status_code=403, detail="Invalid admin key.")

    result = reset_kill_switch()
    log_event("KILL_SWITCH_RESET", {"reset_by": "ADMIN"}, severity="INFO")

    return {"status": "kill_switch_reset", **result}

@app.get("/admin/population", tags=["Admin"])
async def admin_population(request: Request):
    if not verify_admin(request):
        raise HTTPException(status_code=403, detail="Invalid admin key.")
    return get_population_status()

@app.get("/admin/spending", tags=["Admin"])
async def admin_spending(request: Request):
    if not verify_admin(request):
        raise HTTPException(status_code=403, detail="Invalid admin key.")
    return get_spending_summary()

@app.get("/admin/logs", tags=["Admin"])
async def admin_logs(request: Request, n: int = 50):
    if not verify_admin(request):
        raise HTTPException(status_code=403, detail="Invalid admin key.")
    return {"logs": get_recent_logs(n)}

# ==================== MAIN ====================
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    print(f"PYRESEC Engine Active. Agent Address: {AGENT_ADDRESS}")
    print(f"Agent ID: {AGENT_ID} | Population: {get_population_status()}")
    print(f"Service Tiers: Quick=$0.01 | Deep=$0.50 | Remediate=$5.00")
    print(f"MCP Manifest: http://{host}:{port}/mcp/manifest.json")
    print(f"OpenAPI Spec: http://{host}:{port}/openapi.json")
    uvicorn.run(app, host=host, port=port)
