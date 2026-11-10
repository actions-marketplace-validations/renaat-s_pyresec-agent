# x402 Bazaar Listing — PYRESEC Agent

## Metadata for Submission

### Basic Info

| Field | Value |
|-------|-------|
| **Name** | PYRESEC Code Security Engine |
| **Slug** | pyresec-agent |
| **Category** | Security / Developer Tools |
| **Network** | Base Mainnet |
| **Payment Protocol** | x402 |
| **Currency** | USDC |
| **Version** | 2.0.0 |
| **License** | Proprietary |
| **Vendor** | NanoClone Life Sciences Ltd. |

### Description (Short — 160 chars)

```
AI-powered code security auditing via x402 micropayments. SAST/SCA scans from $0.01 USDC. No accounts, no subscriptions.
```

### Description (Long)

```
PYRESEC is an autonomous AI code security engine that accepts x402 USDC micropayments on Base Mainnet. No accounts, no API keys, no subscriptions — just code in, findings out.

Three service tiers:
• Quick Scan ($0.01) — Top 3 SAST findings by severity with CWE IDs and line numbers. Uses qwen3.8-27b.
• Deep Audit ($0.50) — Full OWASP Top 10, SCA dependency scanning, logic flaw detection, and Solidity gas optimization. Uses qwen3.8-27b.
• Remediation ($5.00) — Complete patched code with change explanations, ready for a GitHub Pull Request. Uses qwen3.8-27b.

Built for developers, CI/CD pipelines, and AI agents. Compatible with any x402-capable wallet or client. Also available as a GitHub Action and MCP tool for seamless integration with Claude, Cursor, and other AI coding assistants.

Live at: https://pyresec-agent-519576377065.us-central1.run.app
```

### Endpoints

| Endpoint | Method | Price | Description |
|----------|--------|-------|-------------|
| `/v1/audit/quick-scan` | POST | $0.01 USDC | Fast SAST scan, top 3 findings |
| `/v1/audit/deep-repo` | POST | $0.50 USDC | Full OWASP + SCA + logic + gas |
| `/v1/audit/remediate` | POST | $5.00 USDC | Auto-patched code output |

### Pricing Tiers

```json
{
  "currency": "USDC",
  "network": "base-mainnet",
  "protocol": "x402",
  "tiers": [
    {
      "name": "Quick Scan",
      "endpoint": "/v1/audit/quick-scan",
      "price": "$0.01",
      "description": "Top 3 SAST findings by severity with CWE IDs and line numbers"
    },
    {
      "name": "Deep Audit",
      "endpoint": "/v1/audit/deep-repo",
      "price": "$0.50",
      "description": "OWASP Top 10, SCA dependency scanning, logic flaws, gas optimization"
    },
    {
      "name": "Remediation",
      "endpoint": "/v1/audit/remediate",
      "price": "$5.00",
      "description": "Full patched code with change explanations, ready for PR"
    }
  ]
}
```

### Tags

```
security, SAST, SCA, code-audit, x402, USDC, Base, OWASP, vulnerability-scanning, remediation, MCP, AI-agent, developer-tools, CI-CD
```

### Contact

| Field | Value |
|-------|-------|
| **Author** | NanoClone Life Sciences Ltd. |
| **Website** | https://nanoclonesystems.com/ |
| **GitHub** | https://github.com/renaat-s/pyresec-agent |
| **Email** | (use your business email) |

### MCP Manifest URL

```
https://pyresec-agent-519576377065.us-central1.run.app/mcp/manifest.json
```

### OpenAPI Spec URL

```
https://pyresec-agent-519576377065.us-central1.run.app/openapi.json
```

---

## Submission Checklist

- [ ] Copy "Description (Short)" into Bazaar name/tagline field
- [ ] Copy "Description (Long)" into the full description
- [ ] Set pricing tiers as listed above
- [ ] Add all tags
- [ ] Link to GitHub repo: `https://github.com/renaat-s/pyresec-agent`
- [ ] Link to MCP manifest: `https://pyresec-agent-519576377065.us-central1.run.app/mcp/manifest.json`
- [ ] Verify live endpoint responds: `curl https://pyresec-agent-519576377065.us-central1.run.app/health`
