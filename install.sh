#!/usr/bin/env bash
# install.sh — Install chatnut (one-liner: curl -fsSL ... | bash)
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

# 3. Post-install: register MCP, install skill + rules
chatnut install

echo ""
echo "Done. Restart Claude Code to activate."
