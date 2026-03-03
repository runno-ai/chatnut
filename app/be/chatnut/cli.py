"""CLI entry point for chatnut.

Usage:
    chatnut          # stdio mode (default) — proxy to HTTP server
    chatnut serve    # run HTTP server in foreground
"""
import argparse
import atexit
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx


def _get_run_dir() -> Path:
    """Return the runtime directory for PID/port files."""
    return Path(os.environ.get("CHATNUT_RUN_DIR", Path.home() / ".chatnut"))


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

    pid_file = run_dir / "server.pid"
    pid_file.write_text(str(os.getpid()))

    def cleanup(*_args):
        _cleanup_files(run_dir)
        sys.exit(0)

    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)
    atexit.register(_cleanup_files, run_dir)

    port_file = run_dir / "server.port"

    class _ReadyServer(uvicorn.Server):
        """Uvicorn Server subclass that writes the port file after startup."""

        async def startup(self, sockets=None):
            await super().startup(sockets=sockets)
            if self.started:
                port_file.write_text(str(port))

    config = uvicorn.Config(
        "chatnut.app:app",
        host="127.0.0.1",
        port=port,
        log_level="info",
    )
    server = _ReadyServer(config)
    server.run()


def _is_server_running() -> bool:
    """Check if the HTTP server is alive (PID exists + health check passes)."""
    run_dir = _get_run_dir()
    pid_file = run_dir / "server.pid"
    port_file = run_dir / "server.port"

    if not pid_file.exists() or not port_file.exists():
        return False

    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)
    except (OSError, ValueError):
        _cleanup_files(run_dir)
        return False

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
    """Ensure the HTTP server is running. Returns the server URL."""
    if _is_server_running():
        url = _get_server_url()
        if url:
            return url

    run_dir = _get_run_dir()
    run_dir.mkdir(parents=True, exist_ok=True)

    # Redirect server output to a log file for debugging
    log_file = run_dir / "server.log"
    log_fh = open(log_file, "a")  # noqa: SIM115
    subprocess.Popen(
        [sys.executable, "-m", "chatnut.cli", "serve"],
        stdout=log_fh,
        stderr=log_fh,
        start_new_session=True,
    )
    log_fh.close()

    port_file = run_dir / "server.port"
    for _ in range(20):
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

    raise RuntimeError("Failed to start chatnut server within 10 seconds")


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


def main() -> None:
    parser = argparse.ArgumentParser(prog="chatnut")
    sub = parser.add_subparsers(dest="command")

    serve_parser = sub.add_parser("serve", help="Run HTTP server in foreground")
    serve_parser.add_argument("--port", type=int, default=0, help="Port to bind (0 = auto)")
    serve_parser.set_defaults(func=cmd_serve)

    parser.set_defaults(func=cmd_stdio)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
