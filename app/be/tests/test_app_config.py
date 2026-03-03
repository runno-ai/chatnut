"""Test STATIC_DIR default resolves to package-internal static/ directory."""
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def test_default_static_dir_is_package_relative():
    """_default_static_dir() returns the package-internal static/ path."""
    import chatnut.app as m

    result = m._default_static_dir()
    # Assert structural property without reimplementing the function.
    assert result.endswith(os.path.join("chatnut", "static")), (
        f"Expected path ending in chatnut/static, got {result!r}"
    )
    # Assert the directory actually exists in the installed package.
    assert Path(result).is_dir(), (
        f"static/ directory does not exist at {result!r} — "
        "check that static/.gitkeep is included in the wheel"
    )


def test_serve_spa_path_traversal_returns_404(tmp_path, monkeypatch):
    """serve_spa rejects symlink-based path traversal with 404."""
    import chatnut.app as app_module

    # Point STATIC_DIR at a temp directory with an index.html
    (tmp_path / "index.html").write_text("<html></html>")
    monkeypatch.setattr(app_module, "STATIC_DIR", str(tmp_path))

    # Create an external temp directory that the symlink escapes to
    outside_dir = tmp_path.parent / "outside"
    outside_dir.mkdir(exist_ok=True)
    (outside_dir / "secret.txt").write_text("secret")
    escape_link = tmp_path / "escape"
    escape_link.symlink_to(outside_dir, target_is_directory=True)

    client = TestClient(app_module.app, raise_server_exceptions=False)
    # The symlink resolves outside STATIC_DIR, so is_relative_to() returns False
    resp = client.get("/escape/secret.txt")
    assert resp.status_code == 404
    assert resp.json() == {"error": "Not found"}


def test_serve_spa_missing_index_returns_503(tmp_path, monkeypatch):
    """serve_spa returns 503 when index.html is absent from STATIC_DIR."""
    import chatnut.app as app_module

    # Point STATIC_DIR at an empty temp directory (no index.html)
    monkeypatch.setattr(app_module, "STATIC_DIR", str(tmp_path))

    client = TestClient(app_module.app, raise_server_exceptions=False)
    resp = client.get("/nonexistent-page")
    assert resp.status_code == 503
    assert resp.json()["error"].startswith("Frontend not built")


def test_static_dir_env_var_expression(tmp_path, monkeypatch):
    """STATIC_DIR env var is applied to module-level STATIC_DIR at import."""
    import importlib

    sentinel = str(tmp_path / "custom-static-dir")
    monkeypatch.setenv("STATIC_DIR", sentinel)
    # Remove cached module so the fresh import picks up the env var.
    # monkeypatch.delitem restores sys.modules["chatnut.app"] after the test.
    monkeypatch.delitem(sys.modules, "chatnut.app", raising=False)
    app_module = importlib.import_module("chatnut.app")
    assert app_module.STATIC_DIR == sentinel


def test_static_dir_monkeypatch_affects_serve_spa(tmp_path, monkeypatch):
    """Monkeypatching STATIC_DIR at module level redirects serve_spa() to a custom dir.

    Also verifies that symlink-based path traversal protection still applies with
    a custom STATIC_DIR — a symlink inside the static dir that escapes to an
    external directory is rejected with 404, consistent with the is_relative_to() guard.
    """
    import chatnut.app as app_module

    # Create a custom static dir with a test file and index.html
    custom_file = tmp_path / "custom.js"
    custom_file.write_text("// custom")
    (tmp_path / "index.html").write_text("<html>custom</html>")

    # Create an external temp directory that the symlink escapes to
    outside_dir = tmp_path.parent / "outside2"
    outside_dir.mkdir(exist_ok=True)
    (outside_dir / "secret.txt").write_text("secret")
    escape_link = tmp_path / "escape"
    escape_link.symlink_to(outside_dir, target_is_directory=True)

    monkeypatch.setattr(app_module, "STATIC_DIR", str(tmp_path))

    client = TestClient(app_module.app, raise_server_exceptions=False)

    # File in custom dir is served
    resp = client.get("/custom.js")
    assert resp.status_code == 200
    assert "custom" in resp.text

    # Symlink-based path traversal is still rejected even with custom STATIC_DIR
    resp = client.get("/escape/secret.txt")
    assert resp.status_code == 404
    assert resp.json() == {"error": "Not found"}
