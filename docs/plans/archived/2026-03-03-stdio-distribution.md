# stdio Auto-Start + PyPI Distribution Implementation Plan

## Context

The agents-chat MCP server requires manual startup before Claude Code can connect via HTTP transport. Users must run `ss`, `uvicorn`, or set up a LaunchAgent — none of which are shippable. Additionally, Streamable HTTP sessions are in-memory only, so server restarts cause "Session not found" errors with no automatic recovery. MCP-17 adds a stdio transport shim that auto-starts the HTTP server, and MCP-11 makes the package installable with a single command.

## Goal

Zero-config MCP registration: users install the package and add a `command`-based MCP entry — the server starts automatically on first use, with a live web UI accessible at a discoverable port.

## Architecture

A new CLI module (`cli.py`) provides two modes: **stdio** (default, spawned by Claude Code) and **serve** (runs the full FastAPI server). The stdio mode checks if the HTTP server is already running via PID file + health check; if not, it spawns `serve` as a background daemon, then proxies MCP requests via FastMCP's `ProxyProvider`. The `serve` mode binds to a dynamic high port, writes PID and port to `~/.agents-chat/`, and runs the existing FastAPI app.

## Affected Areas

- Backend: `agents_chat_mcp/cli.py` (new), `pyproject.toml`, `agents_chat_mcp/app.py`
- Project root: `install.sh` (new), `README.md`, `SKILL.md`

## Key Files

- `app/be/agents_chat_mcp/cli.py` — New CLI entry point (core of MCP-17)
- `app/be/pyproject.toml` — `[project.scripts]` entry + click dependency
- `app/be/agents_chat_mcp/app.py` — Minor: extract server startup for reuse
- `install.sh` — New bash install script (MCP-11)
- `README.md` — Updated installation + MCP registration docs

## Reusable Utilities

- `agents_chat_mcp.config:DB_PATH` — existing config module for paths
- `agents_chat_mcp.app:app` — existing FastAPI app instance
- `fastmcp.server.providers.proxy:ProxyProvider,ProxyClient` — stdio→HTTP bridge
- `fastmcp.FastMCP:run_stdio_async()` — stdio transport runner

---

## Tasks

### Task 1: CLI Module — `serve` Subcommand

**Files:**
- Create: `app/be/agents_chat_mcp/cli.py`
- Modify: `app/be/pyproject.toml`
- Test: `app/be/tests/test_cli.py`

**Step 1: Write the failing test**
```python
# tests/test_cli.py
"""Tests for CLI entry point."""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

AGENTS_DIR = Path.home() / ".agents-chat"
PID_FILE = AGENTS_DIR / "server.pid"
PORT_FILE = AGENTS_DIR / "server.port"


class TestServeCommand:
    """Test the 'serve' subcommand."""

    def test_serve_writes_pid_and_port_files(self, tmp_path, monkeypatch):
        """serve writes PID and port files, then cleans up on SIGTERM."""
        pid_file = tmp_path / "server.pid"
        port_file = tmp_path / "server.port"
        monkeypatch.setenv("AGENTS_CHAT_RUN_DIR", str(tmp_path))

        proc = subprocess.Popen(
            [sys.executable, "-m", "agents_chat_mcp.cli", "serve"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        # Wait for server to start (poll port file)
        for _ in range(30):
            if port_file.exists():
                break
            time.sleep(0.5)
        else:
            proc.kill()
            pytest.fail("Port file never written")

        assert pid_file.exists()
        pid = int(pid_file.read_text().strip())
        assert pid == proc.pid

        port = int(port_file.read_text().strip())
        assert 1024 < port < 65536

        # Health check
        resp = httpx.get(f"http://127.0.0.1:{port}/api/status", timeout=5)
        assert resp.status_code == 200

        # Clean shutdown
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=10)

        # Files cleaned up
        assert not pid_file.exists()
        assert not port_file.exists()

    def test_serve_finds_free_port(self, tmp_path, monkeypatch):
        """serve binds to a free high port, not 8000."""
        monkeypatch.setenv("AGENTS_CHAT_RUN_DIR", str(tmp_path))
        port_file = tmp_path / "server.port"

        proc = subprocess.Popen(
            [sys.executable, "-m", "agents_chat_mcp.cli", "serve"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for _ in range(30):
            if port_file.exists():
                break
            time.sleep(0.5)
        else:
            proc.kill()
            pytest.fail("Port file never written")

        port = int(port_file.read_text().strip())
        # Should be a high port (ephemeral range)
        assert port != 8000
        assert port > 1024

        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=10)
```

**Step 2: Run test — expect FAIL**
```bash
cd app/be && uv run pytest tests/test_cli.py -xvs
```
Expected: `ModuleNotFoundError: No module named 'agents_chat_mcp.cli'`

**Step 3: Implement minimal code**
```python
# agents_chat_mcp/cli.py
"""CLI entry point for agents-chat-mcp.

Usage:
    agents-chat-mcp          # stdio mode (default) — proxy to HTTP server
    agents-chat-mcp serve    # run HTTP server in foreground
"""
import argparse
import atexit
import os
import signal
import socket
import sys
from pathlib import Path


def _get_run_dir() -> Path:
    """Return the runtime directory for PID/port files."""
    return Path(os.environ.get("AGENTS_CHAT_RUN_DIR", Path.home() / ".agents-chat"))


def _find_free_port() -> int:
    """Find a free high port by binding to port 0."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _cleanup_files(run_dir: Path) -> None:
    """Remove PID and port files."""
    for f in ("server.pid", "server.port"):
        (run_dir / f).unlink(missing_ok=True)


def cmd_serve(args: argparse.Namespace) -> None:
    """Run the full FastAPI server in foreground."""
    import uvicorn

    run_dir = _get_run_dir()
    run_dir.mkdir(parents=True, exist_ok=True)

    port = args.port if args.port else _find_free_port()

    # Write PID and port files
    pid_file = run_dir / "server.pid"
    port_file = run_dir / "server.port"
    pid_file.write_text(str(os.getpid()))
    port_file.write_text(str(port))

    # Register cleanup
    def cleanup(*_args):
        _cleanup_files(run_dir)
        sys.exit(0)

    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)
    atexit.register(_cleanup_files, run_dir)

    uvicorn.run(
        "agents_chat_mcp.app:app",
        host="127.0.0.1",
        port=port,
        log_level="info",
    )


def cmd_stdio(args: argparse.Namespace) -> None:
    """Run as stdio MCP proxy — auto-starts HTTP server if needed."""
    # Implemented in Task 2
    raise NotImplementedError("stdio mode not yet implemented")


def main() -> None:
    parser = argparse.ArgumentParser(prog="agents-chat-mcp")
    sub = parser.add_subparsers(dest="command")

    serve_parser = sub.add_parser("serve", help="Run HTTP server in foreground")
    serve_parser.add_argument("--port", type=int, default=0, help="Port to bind (0 = auto)")
    serve_parser.set_defaults(func=cmd_serve)

    # Default: stdio mode
    parser.set_defaults(func=cmd_stdio)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
```

Add to `pyproject.toml`:
```toml
[project.scripts]
agents-chat-mcp = "agents_chat_mcp.cli:main"
```

Add `__main__.py`:
```python
# agents_chat_mcp/__main__.py
"""Allow running as python -m agents_chat_mcp."""
from agents_chat_mcp.cli import main

main()
```

**Step 4: Run test — expect PASS**
```bash
cd app/be && uv run pytest tests/test_cli.py -xvs
```

**Step 5: Commit**
```bash
git add app/be/agents_chat_mcp/cli.py app/be/agents_chat_mcp/__main__.py app/be/pyproject.toml app/be/tests/test_cli.py
git commit -m "feat(cli): add serve subcommand with PID/port file management (MCP-17)"
```

---

### Task 2: CLI Module — `stdio` Subcommand (Proxy Mode)

**Files:**
- Modify: `app/be/agents_chat_mcp/cli.py`
- Test: `app/be/tests/test_cli.py`

**Step 1: Write the failing test**
```python
# Append to tests/test_cli.py

class TestServerLifecycle:
    """Test server lifecycle helpers."""

    def test_is_server_running_false_no_pid_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENTS_CHAT_RUN_DIR", str(tmp_path))
        from agents_chat_mcp.cli import _is_server_running
        assert _is_server_running() is False

    def test_is_server_running_false_stale_pid(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENTS_CHAT_RUN_DIR", str(tmp_path))
        (tmp_path / "server.pid").write_text("999999999")  # non-existent PID
        (tmp_path / "server.port").write_text("12345")
        from agents_chat_mcp.cli import _is_server_running
        assert _is_server_running() is False

    def test_get_server_url_from_port_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENTS_CHAT_RUN_DIR", str(tmp_path))
        (tmp_path / "server.port").write_text("4567")
        from agents_chat_mcp.cli import _get_server_url
        assert _get_server_url() == "http://127.0.0.1:4567"

    def test_get_server_url_none_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENTS_CHAT_RUN_DIR", str(tmp_path))
        from agents_chat_mcp.cli import _get_server_url
        assert _get_server_url() is None
```

**Step 2: Run test — expect FAIL**
```bash
cd app/be && uv run pytest tests/test_cli.py::TestServerLifecycle -xvs
```
Expected: `ImportError: cannot import name '_is_server_running'`

**Step 3: Implement minimal code**

Add to `cli.py`:
```python
import subprocess
import time

import httpx


def _is_server_running() -> bool:
    """Check if the HTTP server is alive (PID exists + health check passes)."""
    run_dir = _get_run_dir()
    pid_file = run_dir / "server.pid"
    port_file = run_dir / "server.port"

    if not pid_file.exists() or not port_file.exists():
        return False

    # Check PID is alive
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)  # signal 0 = check existence
    except (OSError, ValueError):
        # Stale PID file — clean up
        _cleanup_files(run_dir)
        return False

    # Health check
    try:
        port = int(port_file.read_text().strip())
        resp = httpx.get(f"http://127.0.0.1:{port}/api/status", timeout=2)
        return resp.status_code == 200
    except Exception:
        return False


def _get_server_url() -> str | None:
    """Read server URL from port file."""
    port_file = _get_run_dir() / "server.port"
    if not port_file.exists():
        return None
    try:
        port = int(port_file.read_text().strip())
        return f"http://127.0.0.1:{port}"
    except (ValueError, OSError):
        return None


def _ensure_server() -> str:
    """Ensure the HTTP server is running. Returns the server URL.

    If not running, spawns 'agents-chat-mcp serve' as a background process
    and waits for health check to pass.
    """
    if _is_server_running():
        url = _get_server_url()
        if url:
            return url

    # Spawn server in background
    subprocess.Popen(
        [sys.executable, "-m", "agents_chat_mcp.cli", "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,  # detach from parent
    )

    # Wait for server to come up (poll port file + health check)
    run_dir = _get_run_dir()
    port_file = run_dir / "server.port"
    for _ in range(20):  # 10 seconds max
        time.sleep(0.5)
        if port_file.exists():
            url = _get_server_url()
            if url:
                try:
                    resp = httpx.get(f"{url}/api/status", timeout=2)
                    if resp.status_code == 200:
                        return url
                except Exception:
                    continue

    raise RuntimeError("Failed to start agents-chat-mcp server within 10 seconds")


def cmd_stdio(args: argparse.Namespace) -> None:
    """Run as stdio MCP proxy — auto-starts HTTP server if needed."""
    import asyncio

    from fastmcp import FastMCP
    from fastmcp.server.providers.proxy import ProxyClient, ProxyProvider

    server_url = _ensure_server()
    mcp_url = f"{server_url}/mcp/"

    proxy = FastMCP("agents-chat")
    proxy.add_provider(ProxyProvider(lambda: ProxyClient(mcp_url)))

    asyncio.run(proxy.run_stdio_async())
```

**Step 4: Run test — expect PASS**
```bash
cd app/be && uv run pytest tests/test_cli.py -xvs
```

**Step 5: Commit**
```bash
git add app/be/agents_chat_mcp/cli.py app/be/tests/test_cli.py
git commit -m "feat(cli): add stdio proxy mode with auto-start (MCP-17)"
```

---

### Task 3: Add `httpx` to Dependencies

**Files:**
- Modify: `app/be/pyproject.toml`

**Step 1: Write the failing test**
The CLI uses `httpx` for health checks. It's already a test dependency but must be a runtime dependency for the CLI.

**Step 3: Implement**
Add `httpx` to `dependencies` in `pyproject.toml`:
```toml
dependencies = [
    "fastmcp>=3.0.0,<4",
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.34.0",
    "sse-starlette>=2.0.0",
    "anyio>=4.0",
    "httpx>=0.28.0",
]
```

**Step 5: Commit**
```bash
git add app/be/pyproject.toml
git commit -m "build: add httpx to runtime deps for CLI health checks"
```

---

### Task 4: Install Script (`install.sh`)

**Files:**
- Create: `install.sh`
- Test: Manual validation

**Step 3: Implement**
```bash
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
echo "Or for Claude Desktop (~/.config/claude/claude_desktop_config.json):"
echo ""
echo '  "agents-chat": {'
echo "    \"command\": \"$BIN\","
echo '    "args": []'
echo '  }'
echo ""
echo "The server starts automatically on first MCP connection."
echo "Web UI available at the port shown in ~/.agents-chat/server.port"
```

**Step 5: Commit**
```bash
chmod +x install.sh
git add install.sh
git commit -m "feat: add one-liner install script (MCP-11)"
```

---

### Task 5: Update README + MCP Registration Docs

**Files:**
- Modify: `README.md`

**Step 3: Implement**

Update the Installation section:
```markdown
## Installation

### One-liner
```bash
curl -fsSL https://raw.githubusercontent.com/runno-ai/agents-chat-mcp/main/install.sh | bash
```

### Manual
```bash
pip install agents-chat-mcp
```

## MCP registration

Add to your MCP client config:

```json
{
  "agents-chat": {
    "command": "agents-chat-mcp"
  }
}
```

The server starts automatically on first connection. No manual startup needed.

**Web UI:** Open `http://127.0.0.1:<port>` — check `~/.agents-chat/server.port` for the port.

**Manual server mode** (if you prefer HTTP transport):
```bash
agents-chat-mcp serve --port 8000
```
Then register as HTTP:
```json
{
  "agents-chat": {
    "url": "http://localhost:8000/mcp/"
  }
}
```
```

**Step 5: Commit**
```bash
git add README.md
git commit -m "docs: update installation + MCP registration for stdio transport (MCP-17, MCP-11)"
```

---

### Task 6: Update SKILL.md — Browser Auto-Open + Server Recovery

**Files:**
- Modify: `SKILL.md`

**Step 3: Implement**

Add to the Setup section after `init_room`:
```markdown
### Auto-Open Web UI

After `init_room`, open the browser to the chatroom:

```bash
PORT=$(cat ~/.agents-chat/server.port 2>/dev/null || echo "8000")
open "http://127.0.0.1:${PORT}/?room=${ROOM_ID}"
```

### Server Recovery

If any `mcp__agents-chat__*` tool call fails with a connection or session error:

1. Check server health: `curl -s http://127.0.0.1:$(cat ~/.agents-chat/server.port)/api/status`
2. If unreachable, restart: `agents-chat-mcp serve &` (or `kill -TERM $(cat ~/.agents-chat/server.pid)` first)
3. Wait up to 10s for health check to pass
4. Retry the failed tool call once
5. Only fall back to SendMessage if recovery also fails
```

**Step 5: Commit**
```bash
git add SKILL.md
git commit -m "docs(skill): add browser auto-open + server recovery instructions (MCP-17)"
```

---

### Phase 7: Documentation Update

- [ ] Update CLAUDE.md with new CLI commands and MCP registration
- [ ] Docstrings for all new public functions in cli.py
- [ ] Update RELEASING.md if install.sh needs PyPI published first

---

## Verification

```bash
# Backend tests
cd app/be && uv run pytest -xvs

# Frontend tests (unchanged but verify no breakage)
cd app/fe && bun run test

# Manual E2E: stdio mode
echo '{}' | agents-chat-mcp  # should auto-start server and respond via stdio

# Manual E2E: serve mode
agents-chat-mcp serve --port 9999 &
curl http://127.0.0.1:9999/api/status  # should return {"status": "ok"}
cat ~/.agents-chat/server.port          # should show 9999
cat ~/.agents-chat/server.pid           # should show server PID
kill %1                                  # cleanup should remove files
```

Expected: All tests pass, stdio proxy auto-starts server, serve writes PID/port files, cleanup works on shutdown.
