"""Tests for CLI entry point."""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest


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

        resp = httpx.get(f"http://127.0.0.1:{port}/api/status", timeout=5)
        assert resp.status_code == 200

        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=10)

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
        assert port != 8000
        assert port > 1024

        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=10)


class TestServerLifecycle:
    """Test server lifecycle helpers."""

    def test_is_server_running_false_no_pid_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENTS_CHAT_RUN_DIR", str(tmp_path))
        from agents_chat_mcp.cli import _is_server_running
        assert _is_server_running() is False

    def test_is_server_running_false_stale_pid(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENTS_CHAT_RUN_DIR", str(tmp_path))
        (tmp_path / "server.pid").write_text("999999999")
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


class TestHelpers:
    """Test small helper functions."""

    def test_find_free_port_returns_high_port(self):
        from agents_chat_mcp.cli import _find_free_port
        port = _find_free_port()
        assert isinstance(port, int)
        assert port > 1024

    def test_cleanup_files_removes_pid_and_port(self, tmp_path):
        (tmp_path / "server.pid").write_text("12345")
        (tmp_path / "server.port").write_text("9999")
        from agents_chat_mcp.cli import _cleanup_files
        _cleanup_files(tmp_path)
        assert not (tmp_path / "server.pid").exists()
        assert not (tmp_path / "server.port").exists()

    def test_cleanup_files_noop_when_missing(self, tmp_path):
        from agents_chat_mcp.cli import _cleanup_files
        _cleanup_files(tmp_path)  # should not raise

    def test_get_run_dir_default(self, monkeypatch):
        monkeypatch.delenv("AGENTS_CHAT_RUN_DIR", raising=False)
        from agents_chat_mcp.cli import _get_run_dir
        result = _get_run_dir()
        assert str(result).endswith(".agents-chat")

    def test_get_run_dir_from_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENTS_CHAT_RUN_DIR", str(tmp_path))
        from agents_chat_mcp.cli import _get_run_dir
        assert _get_run_dir() == tmp_path
