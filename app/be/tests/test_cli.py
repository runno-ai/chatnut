"""Tests for CLI entry point."""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest


class TestServeCommand:
    """Test the 'serve' subcommand."""

    def test_serve_writes_pid_and_port_files(self, tmp_path, monkeypatch):
        """serve writes PID and port files, then cleans up on SIGTERM."""
        pid_file = tmp_path / "server.pid"
        port_file = tmp_path / "server.port"
        monkeypatch.setenv("CHATNUT_RUN_DIR", str(tmp_path))

        proc = subprocess.Popen(
            [sys.executable, "-m", "chatnut.cli", "serve"],
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
        monkeypatch.setenv("CHATNUT_RUN_DIR", str(tmp_path))
        port_file = tmp_path / "server.port"

        proc = subprocess.Popen(
            [sys.executable, "-m", "chatnut.cli", "serve"],
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
        monkeypatch.setenv("CHATNUT_RUN_DIR", str(tmp_path))
        from chatnut.cli import _is_server_running
        assert _is_server_running() is False

    def test_is_server_running_false_stale_pid(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CHATNUT_RUN_DIR", str(tmp_path))
        (tmp_path / "server.pid").write_text("999999999")
        (tmp_path / "server.port").write_text("12345")
        from chatnut.cli import _is_server_running
        assert _is_server_running() is False

    def test_get_server_url_from_port_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CHATNUT_RUN_DIR", str(tmp_path))
        (tmp_path / "server.port").write_text("4567")
        from chatnut.cli import _get_server_url
        assert _get_server_url() == "http://127.0.0.1:4567"

    def test_get_server_url_none_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CHATNUT_RUN_DIR", str(tmp_path))
        from chatnut.cli import _get_server_url
        assert _get_server_url() is None


class TestHelpers:
    """Test small helper functions."""

    def test_find_free_port_returns_high_port(self):
        from chatnut.cli import _find_free_port
        port = _find_free_port()
        assert isinstance(port, int)
        assert port > 1024

    def test_cleanup_files_removes_pid_and_port(self, tmp_path):
        (tmp_path / "server.pid").write_text("12345")
        (tmp_path / "server.port").write_text("9999")
        from chatnut.cli import _cleanup_files
        _cleanup_files(tmp_path)
        assert not (tmp_path / "server.pid").exists()
        assert not (tmp_path / "server.port").exists()

    def test_cleanup_files_noop_when_missing(self, tmp_path):
        from chatnut.cli import _cleanup_files
        _cleanup_files(tmp_path)  # should not raise

    def test_get_run_dir_default(self, monkeypatch):
        monkeypatch.delenv("CHATNUT_RUN_DIR", raising=False)
        from chatnut.cli import _get_run_dir
        result = _get_run_dir()
        assert str(result).endswith(".chatnut")

    def test_get_run_dir_from_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CHATNUT_RUN_DIR", str(tmp_path))
        from chatnut.cli import _get_run_dir
        assert _get_run_dir() == tmp_path


class TestOpenCommand:
    """Test the 'open' subcommand."""

    def test_cmd_open_opens_browser(self, tmp_path, monkeypatch):
        """cmd_open opens browser with server URL."""
        monkeypatch.setenv("CHATNUT_RUN_DIR", str(tmp_path))
        (tmp_path / "server.port").write_text("5555")
        (tmp_path / "server.pid").write_text(str(os.getpid()))

        from chatnut.cli import cmd_open

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        args = MagicMock()
        args.room_id = None
        args.url_only = False

        with patch("chatnut.cli.httpx.get", return_value=mock_resp), \
             patch("webbrowser.open") as mock_browser:
            cmd_open(args)

        mock_browser.assert_called_once_with("http://127.0.0.1:5555")

    def test_cmd_open_with_room_id(self, tmp_path, monkeypatch):
        """cmd_open appends room_id to URL."""
        monkeypatch.setenv("CHATNUT_RUN_DIR", str(tmp_path))
        (tmp_path / "server.port").write_text("5555")
        (tmp_path / "server.pid").write_text(str(os.getpid()))

        from chatnut.cli import cmd_open

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        args = MagicMock()
        args.room_id = "abc-123"
        args.url_only = False

        with patch("chatnut.cli.httpx.get", return_value=mock_resp), \
             patch("webbrowser.open") as mock_browser:
            cmd_open(args)

        mock_browser.assert_called_once_with("http://127.0.0.1:5555/?room=abc-123")

    def test_cmd_open_url_only(self, tmp_path, monkeypatch, capsys):
        """cmd_open --url-only prints URL instead of opening browser."""
        monkeypatch.setenv("CHATNUT_RUN_DIR", str(tmp_path))
        (tmp_path / "server.port").write_text("5555")
        (tmp_path / "server.pid").write_text(str(os.getpid()))

        from chatnut.cli import cmd_open

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        args = MagicMock()
        args.room_id = "abc-123"
        args.url_only = True

        with patch("chatnut.cli.httpx.get", return_value=mock_resp), \
             patch("webbrowser.open") as mock_browser:
            cmd_open(args)

        mock_browser.assert_not_called()
        captured = capsys.readouterr()
        assert "http://127.0.0.1:5555/?room=abc-123" in captured.out


class TestEnsureServer:
    """Test _ensure_server auto-start logic."""

    def test_ensure_server_returns_url_when_running(self, tmp_path, monkeypatch):
        """_ensure_server returns URL immediately if server is already running."""
        monkeypatch.setenv("CHATNUT_RUN_DIR", str(tmp_path))
        (tmp_path / "server.port").write_text("5555")
        (tmp_path / "server.pid").write_text(str(os.getpid()))

        from chatnut.cli import _ensure_server

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("chatnut.cli.httpx.get", return_value=mock_resp):
            url = _ensure_server()

        assert url == "http://127.0.0.1:5555"

    def test_ensure_server_starts_server_when_not_running(self, tmp_path, monkeypatch):
        """_ensure_server spawns a background server and waits for port file."""
        monkeypatch.setenv("CHATNUT_RUN_DIR", str(tmp_path))

        from chatnut.cli import _ensure_server

        mock_popen = MagicMock()
        call_count = 0

        def fake_get(url, timeout=None):
            nonlocal call_count
            call_count += 1
            if "/api/status" in url:
                if "5555" in url:
                    resp = MagicMock()
                    resp.status_code = 200
                    return resp
                # _is_server_running check — no port file yet
                raise httpx.ConnectError("refused")
            raise httpx.ConnectError("refused")

        def fake_popen(*args, **kwargs):
            # Simulate server writing port file after Popen
            (tmp_path / "server.port").write_text("5555")
            return mock_popen

        with patch("chatnut.cli.subprocess.Popen", side_effect=fake_popen) as popen_mock, \
             patch("chatnut.cli.httpx.get", side_effect=fake_get), \
             patch("chatnut.cli.time.sleep"):
            url = _ensure_server()

        assert url == "http://127.0.0.1:5555"
        popen_mock.assert_called_once()
        # Verify log file was created
        assert (tmp_path / "server.log").exists()

    def test_ensure_server_creates_run_dir(self, tmp_path, monkeypatch):
        """_ensure_server creates the run directory if it doesn't exist."""
        run_dir = tmp_path / "subdir" / "nested"
        monkeypatch.setenv("CHATNUT_RUN_DIR", str(run_dir))

        from chatnut.cli import _ensure_server

        def fake_popen(*args, **kwargs):
            (run_dir / "server.port").write_text("6666")
            return MagicMock()

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("chatnut.cli.subprocess.Popen", side_effect=fake_popen), \
             patch("chatnut.cli.httpx.get", side_effect=[
                 httpx.ConnectError("refused"),  # _is_server_running
                 mock_resp,  # health check after port file appears
             ]), \
             patch("chatnut.cli.time.sleep"):
            url = _ensure_server()

        assert url == "http://127.0.0.1:6666"
        assert run_dir.exists()

    def test_ensure_server_raises_on_timeout(self, tmp_path, monkeypatch):
        """_ensure_server raises RuntimeError if server doesn't start."""
        monkeypatch.setenv("CHATNUT_RUN_DIR", str(tmp_path))

        from chatnut.cli import _ensure_server

        with patch("chatnut.cli.subprocess.Popen", return_value=MagicMock()), \
             patch("chatnut.cli.httpx.get", side_effect=httpx.ConnectError("refused")), \
             patch("chatnut.cli.time.sleep"):
            with pytest.raises(RuntimeError, match="Failed to start"):
                _ensure_server()
