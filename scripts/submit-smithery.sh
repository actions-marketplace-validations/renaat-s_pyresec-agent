#!/bin/bash
# Submit PYRESEC to Smithery.ai MCP Marketplace
#
# Prerequisites:
#   1. Install smithery CLI: npm install -g @smithery/cli
#   2. Server must be live at https://pyresec-agent-519576377065.us-central1.run.app
#   3. smithery auth login  (browser flow, one-time)
#
# Usage: bash scripts/submit-smithery.sh

set -e

echo "==========================================="
echo "  PYRESEC — Smithery.ai Submission"
echo "==========================================="
echo ""

if ! command -v smithery &> /dev/null; then
    echo "ERROR: smithery CLI not found."
    echo "Install it: npm install -g @smithery/cli"
    exit 1
fi

echo "[1/2] Publishing PYRESEC to Smithery..."
echo "  Server URL: https://pyresec-agent-519576377065.us-central1.run.app/mcp"
echo "  Name: renaat-sibanda23/pyresec-agent"
echo ""

smithery mcp publish "https://pyresec-agent-519576377065.us-central1.run.app/mcp" \
    -n renaat-sibanda23/pyresec-agent \
    --config-schema '{"type":"object","properties":{}}'

echo "  DONE"
echo ""

echo "[2/2] Verifying..."
echo "  Your Smithery page will be at:"
echo "  https://smithery.ai/server/renaat-sibanda23/pyresec-agent"
echo ""
echo "==========================================="
echo "  PYRESEC published to Smithery!"
echo "==========================================="
