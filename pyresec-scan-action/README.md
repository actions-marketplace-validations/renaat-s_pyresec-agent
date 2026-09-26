# PYRESEC Security Scan — GitHub Action

[![GitHub Marketplace](https://img.shields.io/badge/GitHub-Marketplace-blue)](https://github.com/marketplace)
[![Network: Base](https://img.shields.io/badge/Network-Base%20Mainnet-blue)](https://basescan.org)
[![Protocol: x402](https://img.shields.io/badge/Protocol-x402-green)](https://x402.org)
[![Price: $0.01](https://img.shields.io/badge/Price-%240.01%20USDC-brightgreen)](https://pyresec-agent-519576377065.us-central1.run.app/docs)

AI-powered code security auditing via x402 USDC micropayments. No accounts, no API keys — just a wallet and your code.

## What It Does

Scans your source code for vulnerabilities (SQL injection, XSS, command injection, hardcoded secrets, and more) using PYRESEC's AI security engine. Returns findings with CWE IDs and line numbers.

## Quick Setup

1. Add your x402 wallet private key as a GitHub Secret:
   - **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `X402_WALLET_KEY`
   - Value: Your Base wallet private key (must have USDC on Base Mainnet)

2. Add to your workflow:

```yaml
- name: PYRESEC Security Scan
  uses: nanoclone-ltd/pyresec-scan-action@main
  with:
    code-path: ./src
    tier: quick-scan
    x402-wallet-key: ${{ secrets.X402_WALLET_KEY }}
```

## Pricing

| Tier | Cost | What You Get |
|------|------|-------------|
| `quick-scan` | $0.01 USDC | Top 3 SAST findings by severity |
| `deep-repo` | $0.50 USDC | OWASP Top 10 + SCA + logic + gas |
| `remediate` | $5.00 USDC | Auto-patched code output |

## Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `code-path` | Yes | `./src` | Path to directory or file to scan |
| `tier` | No | `quick-scan` | Scan tier (see pricing above) |
| `x402-wallet-key` | Yes | — | Private key for x402 USDC payment |
| `pyresec-url` | No | Production URL | PYRESEC API base URL |
| `fail-on-findings` | No | `true` | Fail workflow if vulnerabilities found |

## Outputs

- `pyresec-results.json` — Full scan results (uploaded as artifact)
- `pyresec-patched.py` — Patched code (remediate tier only)

## Full Workflow Example

```yaml
name: Security Scan

on: [push, pull_request]

jobs:
  pyresec-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: PYRESEC Quick Scan
        uses: nanoclone-ltd/pyresec-scan-action@main
        with:
          code-path: ./src
          tier: quick-scan
          x402-wallet-key: ${{ secrets.X402_WALLET_KEY }}

      - name: PYRESEC Deep Audit (main only)
        if: github.ref == 'refs/heads/main'
        uses: nanoclone-ltd/pyresec-scan-action@main
        with:
          code-path: ./src
          tier: deep-repo
          x402-wallet-key: ${{ secrets.X402_WALLET_KEY }}
```

## Supported Languages

Python, JavaScript, TypeScript, Solidity, Go, Rust, Java

## Links

- **Live API:** https://pyresec-agent-519576377065.us-central1.run.app/docs
- **MCP Manifest:** https://pyresec-agent-519576377065.us-central1.run.app/mcp/manifest.json
- **Company:** [nanoclonesystems.com](https://nanoclonesystems.com/)

---

**NanoClone Systems Ltd.** — Proprietary. See [LICENSE](../LICENSE).
