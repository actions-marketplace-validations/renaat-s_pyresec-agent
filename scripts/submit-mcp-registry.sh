#!/bin/bash
# Submit PYRESEC to the Official MCP Registry
#
# Prerequisites:
#   1. Install mcp-publisher: https://github.com/modelcontextprotocol/registry/releases
#      (this machine: $LOCALAPPDATA\mcp-publisher.exe)
#   2. GitHub repo public at https://github.com/renaat-s/pyresec-agent
#
# Usage: bash scripts/submit-mcp-registry.sh

set -e

echo "==========================================="
echo "  PYRESEC — MCP Registry Submission"
echo "==========================================="
echo ""

PUB="mcp-publisher"
if ! command -v "$PUB" &> /dev/null; then
    if [ -f "$LOCALAPPDATA/mcp-publisher.exe" ]; then
        PUB="$LOCALAPPDATA/mcp-publisher.exe"
    else
        echo "ERROR: mcp-publisher not found."
        echo "Install: https://github.com/modelcontextprotocol/registry/releases"
        exit 1
    fi
fi

echo "[1/4] Validating server.json..."
"$PUB" validate server.json
echo "  OK - server.json is valid"
echo ""

echo "[2/4] Authenticating (GitHub device flow)..."
echo "  One-time: opens https://github.com/login/device in your browser."
echo "  Allowed namespace after auth: io.github.renaat-s/*"
echo ""
"$PUB" login github
echo ""

echo "[3/4] Publishing to MCP Registry..."
echo "  Name: io.github.renaat-s/pyresec-agent"
echo ""
"$PUB" publish server.json
echo "  DONE"
echo ""

echo "[4/4] Verifying..."
echo "  https://registry.modelcontextprotocol.io/v0.1/servers?search=pyresec"
echo ""
echo "==========================================="
echo "  PYRESEC published to MCP Registry!"
echo "==========================================="
