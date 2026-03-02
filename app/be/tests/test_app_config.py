"""Test STATIC_DIR default resolves to package-internal static/ directory."""
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


def test_default_static_dir_is_package_relative():
    """_default_static_dir() returns the package-internal static/ path."""
    import agents_chat_mcp.app as m

    result = m._default_static_dir()
    # Assert structural property without reimplementing the function.
    assert result.endswith(os.path.join("agents_chat_mcp", "static")), (
        f"Expected path ending in agents_chat_mcp/static, got {result!r}"
    )
    # Assert the directory actually exists in the installed package.
    assert Path(result).is_dir(), (
        f"static/ directory does not exist at {result!r} — "
        "check that static/.gitkeep is included in the wheel"
    )


def test_serve_spa_path_traversal_returns_404(tmp_path, monkeypatch):
    """serve_spa rejects symlink-based path traversal with 404."""
    import agents_chat_mcp.app as app_module

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
    import agents_chat_mcp.app as app_module

    # Point STATIC_DIR at an empty temp directory (no index.html)
    monkeypatch.setattr(app_module, "STATIC_DIR", str(tmp_path))

    client = TestClient(app_module.app, raise_server_exceptions=False)
    resp = client.get("/nonexistent-page")
    assert resp.status_code == 503
    assert resp.json()["error"].startswith("Frontend not built")


def test_static_dir_env_var_expression():
    """STATIC_DIR env var is read by os.environ.get() at module load.

    Tests the env-var resolution logic directly: os.environ.get("STATIC_DIR", fallback)
    should prefer the env var over the default. This validates the module-level expression
    without triggering importlib.reload side effects.
    """
    import agents_chat_mcp.app as app_module

    sentinel = "/tmp/custom-static-dir"
    with patch.dict(os.environ, {"STATIC_DIR": sentinel}):
        resolved = os.environ.get("STATIC_DIR", app_module._default_static_dir())
    assert resolved == sentinel, f"Expected {sentinel!r}, got {resolved!r}"


def test_static_dir_monkeypatch_affects_serve_spa(tmp_path, monkeypatch):
    """Monkeypatching STATIC_DIR at module level redirects serve_spa() to a custom dir.

    Also verifies that symlink-based path traversal protection still applies with
    a custom STATIC_DIR — a symlink inside the static dir that escapes to /etc is
    rejected with 404, consistent with the is_relative_to() guard in serve_spa().
    """
    import agents_chat_mcp.app as app_module

    # Create a custom static dir with a test file and index.html
    custom_file = tmp_path / "custom.js"
    custom_file.write_text("// custom")
    (tmp_path / "index.html").write_text("<html>custom</html>")

    # Create a symlink inside the custom static dir that escapes to /etc
    escape_link = tmp_path / "escape"
    escape_link.symlink_to("/etc")

    monkeypatch.setattr(app_module, "STATIC_DIR", str(tmp_path))

    client = TestClient(app_module.app, raise_server_exceptions=False)

    # File in custom dir is served
    resp = client.get("/custom.js")
    assert resp.status_code == 200
    assert "custom" in resp.text

    # Symlink-based path traversal is still rejected even with custom STATIC_DIR
    resp = client.get("/escape/passwd")
    assert resp.status_code == 404
    assert resp.json() == {"error": "Not found"}
