#!/bin/bash
# Start agents-chat MCP server via portless.
# PORT env var is set by portless before invoking this script.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/../app/be"

exec .venv/bin/python -m uvicorn chatnut.app:app --port "$PORT"
