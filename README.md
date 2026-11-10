# PYRESEC — AI Code Security Engine

> Autonomous SAST/SCA security auditing via x402 USDC micropayments on Base. No subscriptions. No accounts. Just code in, findings out.

[![Network: Base](https://img.shields.io/badge/Network-Base%20Mainnet-blue)](https://basescan.org)
[![Protocol: x402](https://img.shields.io/badge/Protocol-x402-green)](https://x402.org)
[![MCP Compatible](https://img.shields.io/badge/MCP-Compatible-purple)](https://modelcontextprotocol.io)
[![License: Proprietary](https://img.shields.io/badge/License-Proprietary-red)](https://pyresec.io/license)

## Live Instance

| Endpoint | URL |
|----------|-----|
| **Landing** | [pyresec-agent-519576377065.us-central1.run.app](https://pyresec-agent-519576377065.us-central1.run.app/docs) |
| **Swagger UI** | [/swagger](https://pyresec-agent-519576377065.us-central1.run.app/swagger) |
| **Health** | [/health](https://pyresec-agent-519576377065.us-central1.run.app/health) |
| **MCP Manifest** | [/mcp/manifest.json](https://pyresec-agent-519576377065.us-central1.run.app/mcp/manifest.json) |
| **OpenAPI Spec** | [/openapi.json](https://pyresec-agent-519576377065.us-central1.run.app/openapi.json) |

---

## Quick Start

### Option 1: x402 Python Client (Recommended)

```bash
pip install x402
```

```python
import x402

client = x402.Client(wallet_key="your-base-private-key")
response = client.post(
    "https://pyresec-agent-519576377065.us-central1.run.app/v1/audit/quick-scan",
    json={"code": "def login(u,p): return db.query(f\"SELECT * FROM users WHERE name={u} AND pass={p}\")"}
)
print(response.json())
```

### Option 2: curl (Manual x402 Flow)

```bash
# Step 1: Send request (returns 402 with payment requirements)
curl -X POST https://pyresec-agent-519576377065.us-central1.run.app/v1/audit/quick-scan \
  -H "Content-Type: application/json" \
  -d '{"code": "def login(u,p): return db.query(f\"SELECT * FROM users WHERE name={u} AND pass={p}\")"}'

# Step 2: Pay $0.01 USDC on Base using x402 protocol

# Step 3: Resubmit with X-PAYMENT header
curl -X POST https://pyresec-agent-519576377065.us-central1.run.app/v1/audit/quick-scan \
  -H "Content-Type: application/json" \
  -H "X-PAYMENT: <payment-proof>" \
  -d '{"code": "..."}'
```

### Option 3: GitHub Action (CI/CD)

```yaml
- name: PYRESEC Security Scan
  uses: nanoclone-ltd/pyresec-scan-action@main
  with:
    code-path: ./src
    tier: quick-scan
    x402-wallet-key: ${{ secrets.X402_WALLET_KEY }}
```

### Option 4: MCP-Compatible Agent (Claude, Cursor, etc.)

PYRESEC is a registered MCP tool. Any MCP-compatible client discovers it automatically:

```json
{
  "mcpServers": {
    "pyresec": {
      "url": "https://pyresec-agent-519576377065.us-central1.run.app/mcp"
    }
  }
}
```

---

## Service Tiers

| Tier | Price | Endpoint | Description | Model |
|------|-------|----------|-------------|-------|
| **Quick Scan** | $0.01 | `POST /v1/audit/quick-scan` | Top 3 findings by severity, CWE IDs, line numbers | qwen3.8-27b |
| **Deep Audit** | $0.50 | `POST /v1/audit/deep-repo` | OWASP Top 10, SCA dependency scanning, logic flaws, gas optimization | qwen3.8-27b |
| **Remediation** | $5.00 | `POST /v1/audit/remediate` | Full patched code with change explanations and security notes | qwen3.8-27b |

---

## x402 Payment Flow

PYRESEC uses the [x402 protocol](https://x402.org) for permissionless micropayments on Base. No accounts, no API keys, no subscriptions.

```
┌──────────┐     POST /v1/audit/quick-scan     ┌──────────┐
│  Client   │ ───────────────────────────────▶  │  PYRESEC │
│ (x402)    │ ◀──── 402 Payment Required ─────  │  Agent   │
│           │       { amount, network, to }     │          │
│           │                                   │          │
│           │ ──── X-PAYMENT (proof) ─────────▶ │          │
│           │ ◀──── 200 + Scan Results ──────── │          │
└──────────┘                                   └──────────┘
```

**How it works:**
1. Client sends a POST request to any audit endpoint
2. PYRESEC returns `402 Payment Required` with payment details (amount, recipient address, network)
3. Client signs and submits a USDC transfer on Base mainnet
4. Client resubmits the original request with the `X-PAYMENT` header containing the payment proof
5. PYRESEC verifies the payment on-chain and returns the scan results

**No wallet?** Use the [x402 Python SDK](https://github.com/coinbase/x402) or any x402-compatible client.

---

## Architecture

```
                         ┌─────────────────────────────────┐
                         │          Client Layer            │
                         │  x402 SDK / curl / MCP Client    │
                         └──────────────┬──────────────────┘
                                        │
                              ┌─────────▼─────────┐
                              │   FastAPI Server   │
                              │   (Cloud Run)      │
                              │                    │
                              │  ┌──────────────┐  │
                              │  │ x402 Payment │  │
                              │  │  Middleware   │  │
                              │  └──────┬───────┘  │
                              └─────────┼──────────┘
                                        │
                    ┌───────────────────┼───────────────────┐
                    │                   │                   │
          ┌─────────▼─────────┐ ┌───────▼───────┐ ┌───────▼───────┐
          │  Agent Controller │ │  Population   │ │   Wallet      │
          │  (SAST + LLM)     │ │  Controller   │ │  Interface    │
          └─────────┬─────────┘ └───────────────┘ └───────────────┘
                    │
          ┌─────────▼─────────┐
          │   Groq LLM        │
          │   (qwen models)   │
          └─────────┬─────────┘
                    │
          ┌─────────▼─────────┐
          │  Security Findings │
          │  JSON Response     │
          └───────────────────┘
```

---

## Supported Vulnerability Types

| # | Type | CWE | Severity |
|---|------|-----|----------|
| 1 | SQL Injection | CWE-89 | HIGH |
| 2 | Cross-Site Scripting (XSS) | CWE-79 | HIGH |
| 3 | Command Injection | CWE-78 | CRITICAL |
| 4 | Path Traversal | CWE-22 | MEDIUM |
| 5 | Hardcoded Secrets | CWE-798 | CRITICAL |
| 6 | Weak Cryptography | CWE-327 | MEDIUM |
| 7 | SSRF | CWE-918 | HIGH |
| 8 | Insecure Deserialization | CWE-502 | HIGH |
| 9 | Authentication Bypass | CWE-287 | CRITICAL |
| 10 | Improper Input Validation | CWE-20 | MEDIUM |

---

## For AI Agents (MCP Integration)

PYRESEC is discoverable by any MCP-compatible agent. When an agent needs to audit code, it can find PYRESEC automatically through:

- **MCP Registry**: `registry.modelcontextprotocol.io`
- **Smithery.ai**: `smithery.ai/server/@renaat-s/pyresec-agent`
- **Direct manifest**: `/mcp/manifest.json`

### Tool Definitions

| Tool | Description | Cost |
|------|-------------|------|
| `quick_scan` | Fast SAST scan, top 3 findings by severity with CWE IDs | $0.01 USDC |
| `deep_audit` | Full OWASP Top 10, SCA, logic flaws, gas optimization | $0.50 USDC |
| `remediate_code` | Auto-patched code with change explanations, ready for PR | $5.00 USDC |

### Agent Discovery Flow

```
1. Agent queries MCP Registry for "security audit" tools
2. PYRESEC appears in results with tool schemas
3. Agent calls quick_scan with source code
4. PYRESEC returns 402 with x402 payment requirements
5. Agent's x402 wallet pays USDC on Base
6. Agent resubmits with payment proof
7. PYRESEC returns findings as structured JSON
```

---

## Self-Sustaining Agent

PYRESEC runs as an autonomous agent on Base Mainnet:

- **Heartbeat** every 30 min — checks balance, reports health
- **Death** — shuts down if balance < $0.05
- **Replication** — sends 50% surplus to dev wallet when balance > $20
- **Kill switch** — admin can halt all instances remotely

---

## Deployment

### Docker

```bash
docker build -t pyresec-agent .
docker run -p 8080:8080 --env-file .env pyresec-agent
```

### Google Cloud Run

```bash
gcloud run deploy pyresec-agent \
  --source . \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars "CDP_WALLET_SECRET=$CDP_WALLET_SECRET,GROQ_API_KEY=$GROQ_API_KEY"
```

---

## Company

**NanoClone Life Sciences Ltd.** (UK)
Website: [nanoclonesystems.com](https://nanoclonesystems.com/)

## License

Proprietary. See [LICENSE](LICENSE) for details.
