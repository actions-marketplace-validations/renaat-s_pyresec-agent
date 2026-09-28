"""
PYRESEC MCP Server - Model Context Protocol wrapper for PYRESEC Code Security Engine.

Exposes PYRESEC's security scanning tools via MCP protocol so Claude, Cursor,
and other MCP-compatible agents can discover and use them.

Usage:
    python mcp_server.py

Or as an npm-style entry point:
    npx pyresec-mcp
"""
import json
import sys
import asyncio
import os

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
except ImportError:
    print("ERROR: MCP SDK not installed. Run: pip install mcp", file=sys.stderr)
    sys.exit(1)

import httpx

PYRESEC_URL = os.getenv("PYRESEC_URL", "https://pyresec-agent-519576377065.us-central1.run.app")

server = Server("pyresec-mcp")


@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="pyresec_quick_scan",
            description="Run a fast security scan on source code. Returns top 3 findings with CWE IDs. Costs $0.01 USDC via x402 micropayment.",
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Source code to scan for security vulnerabilities"
                    }
                },
                "required": ["code"]
            }
        ),
        Tool(
            name="pyresec_deep_audit",
            description="Comprehensive security audit: OWASP Top 10, logic flaws, dependency risks, gas optimization for Solidity. Returns detailed report with remediation steps. Costs $0.50 USDC via x402 micropayment.",
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Source code to audit"
                    },
                    "language": {
                        "type": "string",
                        "description": "Programming language (python, javascript, solidity, etc.)"
                    },
                    "dependencies": {
                        "type": "string",
                        "description": "Dependency file contents (requirements.txt, package.json, etc.)"
                    }
                },
                "required": ["code"]
            }
        ),
        Tool(
            name="pyresec_remediate",
            description="Automatically fix security vulnerabilities in code. Returns patched code with explanations. Costs $5.00 USDC via x402 micropayment.",
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Source code to remediate"
                    },
                    "findings": {
                        "type": "string",
                        "description": "JSON string of findings to fix (from quick_scan or deep_audit)"
                    }
                },
                "required": ["code", "findings"]
            }
        ),
        Tool(
            name="pyresec_engagement_remediation",
            description="Proof-led remediation engagement: exhaustive audit, patched code, and a client PDF security report (base64). Costs $500.00 USDC via x402 micropayment.",
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Repository source code for the engagement"
                    },
                    "meta": {
                        "type": "object",
                        "description": "Client metadata: client, repo_url, engagement, contact",
                        "properties": {
                            "client": {"type": "string"},
                            "repo_url": {"type": "string"},
                            "engagement": {"type": "string"},
                            "contact": {"type": "string"},
                        }
                    }
                },
                "required": ["code"]
            }
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    async with httpx.AsyncClient(timeout=120.0) as client:
        endpoint_map = {
            "pyresec_quick_scan": "/v1/audit/quick-scan",
            "pyresec_deep_audit": "/v1/audit/deep-repo",
            "pyresec_remediate": "/v1/audit/remediate",
            "pyresec_engagement_remediation": "/v1/engagement/remediation",
        }

        endpoint = endpoint_map.get(name)
        if not endpoint:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

        try:
            resp = await client.post(
                f"{PYRESEC_URL}{endpoint}",
                json=arguments,
            )

            if resp.status_code == 200:
                result = resp.json()
                return [TextContent(type="text", text=json.dumps(result, indent=2))]
            elif resp.status_code == 402:
                return [TextContent(type="text", text=(
                    "PYRESEC requires x402 micropayment. This MCP server needs an x402-compatible "
                    "payment client to process payments. Install the x402 client or use the "
                    "PYRESEC HTTP API directly with an x402-capable client.\n\n"
                    f"Payment required: {resp.text[:500]}"
                ))]
            else:
                return [TextContent(type="text", text=f"Error {resp.status_code}: {resp.text[:500]}")]

        except httpx.ConnectError:
            return [TextContent(type="text", text="Cannot connect to PYRESEC server. It may be down.")]
        except Exception as e:
            return [TextContent(type="text", text=f"Error: {str(e)}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
