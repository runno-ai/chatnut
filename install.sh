#!/usr/bin/env bash
# install.sh — Install chatnut and register with Claude Code
set -euo pipefail

echo "Installing chatnut..."

# 1. Ensure uv is available
if ! command -v uv &>/dev/null; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

# 2. Install the package
uv tool install chatnut

# 3. Find the installed binary
BIN=$(uv tool dir)/chatnut/bin/chatnut
if [[ ! -x "$BIN" ]]; then
    BIN=$(which chatnut 2>/dev/null || echo "")
fi

if [[ -z "$BIN" ]]; then
    echo "Error: chatnut binary not found after install"
    exit 1
fi

echo ""
echo "Installed successfully!"

# 4. Auto-register with Claude Code (if available)
if command -v claude &>/dev/null; then
    echo ""
    echo "Registering with Claude Code..."
    if claude mcp add chatnut -- "$BIN" 2>/dev/null; then
        echo "  ✓ Registered as 'agents-chat' MCP server"
    else
        echo "  ⚠ Auto-registration failed. Add manually to ~/.claude.json:"
        echo ""
        echo '    "chatnut": {'
        echo "      \"command\": \"$BIN\""
        echo '    }'
    fi
else
    echo ""
    echo "Claude Code not found. Add manually to ~/.claude.json:"
    echo ""
    echo '  "chatnut": {'
    echo "    \"command\": \"$BIN\""
    echo '  }'
fi

# 5. Print Claude Desktop instructions (requires manual config)
if [[ "$(uname)" == "Darwin" ]]; then
    DESKTOP_CONFIG="~/Library/Application Support/Claude/claude_desktop_config.json"
else
    DESKTOP_CONFIG="~/.config/claude/claude_desktop_config.json"
fi
echo ""
echo "For Claude Desktop, add to $DESKTOP_CONFIG:"
echo ""
echo '  "chatnut": {'
echo "    \"command\": \"$BIN\","
echo '    "args": []'
echo '  }'

echo ""
echo "The server starts automatically on first MCP connection."
echo "Web UI available at the port shown in ~/.chatnut/server.port"
