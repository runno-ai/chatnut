#!/usr/bin/env bash
# install.sh — Install agents-chat-mcp and register with Claude Code
set -euo pipefail

echo "Installing agents-chat-mcp..."

# 1. Ensure uv is available
if ! command -v uv &>/dev/null; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

# 2. Install the package
uv tool install agents-chat-mcp

# 3. Find the installed binary
BIN=$(uv tool dir)/agents-chat-mcp/bin/agents-chat-mcp
if [[ ! -x "$BIN" ]]; then
    BIN=$(which agents-chat-mcp 2>/dev/null || echo "")
fi

if [[ -z "$BIN" ]]; then
    echo "Error: agents-chat-mcp binary not found after install"
    exit 1
fi

echo ""
echo "Installed successfully!"
echo ""
echo "Add to your Claude Code MCP config (~/.claude.json):"
echo ""
echo '  "agents-chat": {'
echo "    \"command\": \"$BIN\""
echo '  }'
echo ""
if [[ "$(uname)" == "Darwin" ]]; then
    DESKTOP_CONFIG="~/Library/Application Support/Claude/claude_desktop_config.json"
else
    DESKTOP_CONFIG="~/.config/claude/claude_desktop_config.json"
fi
echo "Or for Claude Desktop ($DESKTOP_CONFIG):"
echo ""
echo '  "agents-chat": {'
echo "    \"command\": \"$BIN\","
echo '    "args": []'
echo '  }'
echo ""
echo "The server starts automatically on first MCP connection."
echo "Web UI available at the port shown in ~/.agents-chat/server.port"
