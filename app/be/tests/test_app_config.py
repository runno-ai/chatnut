"""Test STATIC_DIR default resolves to package-internal static/ directory."""
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def test_default_static_dir_is_package_relative():
    """_default_static_dir() returns the package-internal static/ path."""
    import agent_chat_mcp.app as m

    result = m._default_static_dir()
    # Assert structural property without reimplementing the function.
    assert result.endswith(os.path.join("agent_chat_mcp", "static")), (
        f"Expected path ending in agent_chat_mcp/static, got {result!r}"
    )
    # Assert the directory actually exists in the installed package.
    assert Path(result).is_dir(), (
        f"static/ directory does not exist at {result!r} — "
        "check that static/.gitkeep is included in the wheel"
    )


def test_serve_spa_path_traversal_returns_404(tmp_path, monkeypatch):
    """serve_spa rejects symlink-based path traversal with 404."""
    import agent_chat_mcp.app as app_module

    # Point STATIC_DIR at a temp directory with an index.html
    (tmp_path / "index.html").write_text("<html></html>")
    monkeypatch.setattr(app_module, "STATIC_DIR", str(tmp_path))

    # Create a symlink inside static dir that escapes to /etc
    escape_link = tmp_path / "escape"
    escape_link.symlink_to("/etc")

    client = TestClient(app_module.app, raise_server_exceptions=False)
    # The symlink resolves outside STATIC_DIR, so is_relative_to() returns False
    resp = client.get("/escape/passwd")
    assert resp.status_code == 404
    assert resp.json() == {"error": "Not found"}


def test_serve_spa_missing_index_returns_503(tmp_path, monkeypatch):
    """serve_spa returns 503 when index.html is absent from STATIC_DIR."""
    import agent_chat_mcp.app as app_module

    # Point STATIC_DIR at an empty temp directory (no index.html)
    monkeypatch.setattr(app_module, "STATIC_DIR", str(tmp_path))

    client = TestClient(app_module.app, raise_server_exceptions=False)
    resp = client.get("/nonexistent-page")
    assert resp.status_code == 503
    assert resp.json()["error"].startswith("Frontend not built")
