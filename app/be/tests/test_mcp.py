"""Smoke tests for MCP tool registration."""

import pytest

from chatnut.mcp import mcp


@pytest.mark.anyio
async def test_all_tools_registered():
    """Verify all expected MCP tools are registered."""
    tools = await mcp.list_tools()
    tool_names = {t.name for t in tools}
    expected = {
        "ping", "init_room", "post_message", "read_messages",
        "list_rooms", "archive_room", "delete_room", "clear_room",
        "search", "list_projects", "mark_read", "wait_for_messages",
    }
    assert expected.issubset(tool_names), f"Missing tools: {expected - tool_names}"


@pytest.mark.anyio
async def test_mark_read_tool_registered():
    """Verify mark_read is in the tool list."""
    from chatnut.mcp import mcp
    tools = await mcp.list_tools()
    tool_names = [t.name for t in tools]
    assert "mark_read" in tool_names


def test_ping_uses_live_service_path(db):
    """ping() returns the live service db_path, not the module-level DB_PATH constant."""
    from chatnut import mcp as mcp_module
    from chatnut.service import ChatService

    svc = ChatService(db)
    original_factory = mcp_module._service_factory
    mcp_module.set_service_factory(lambda: svc)
    try:
        result = mcp_module.ping()
        assert result["status"] == "ok"
        assert result["db_path"] == svc.db_path()
    finally:
        mcp_module.set_service_factory(original_factory)


def test_search_route_returns_422_for_empty_query(db):
    """GET /api/search?q= should return 422 for empty query."""
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from chatnut.routes import create_router
    from chatnut.service import ChatService

    svc = ChatService(db)
    test_app = FastAPI()
    router = create_router(lambda: svc)
    test_app.include_router(router)
    client = TestClient(test_app, raise_server_exceptions=False)

    resp = client.get("/api/search", params={"q": ""})
    assert resp.status_code == 422

    resp = client.get("/api/search", params={"q": "   "})
    assert resp.status_code == 422


def test_ping_includes_version(db):
    from unittest.mock import patch
    from chatnut import mcp as mcp_module
    from chatnut.service import ChatService
    from chatnut.version_check import VersionInfo

    svc = ChatService(db)
    original = mcp_module._service_factory
    mcp_module.set_service_factory(lambda: svc)
    try:
        with patch(
            "chatnut.mcp.get_cached_version_info",
            return_value=VersionInfo(current="0.2.0", latest="0.3.0"),
        ):
            result = mcp_module.ping()
        assert result["version"] == "0.2.0"
        assert result["latest"] == "0.3.0"
        assert result["update_available"] is True
    finally:
        mcp_module.set_service_factory(original)


def test_ping_includes_web_url_when_port_file_exists(db, tmp_path, monkeypatch):
    """ping() includes web_url when server.port file exists."""
    from unittest.mock import patch
    from chatnut import mcp as mcp_module
    from chatnut.service import ChatService
    from chatnut.version_check import VersionInfo

    monkeypatch.setenv("CHATNUT_RUN_DIR", str(tmp_path))
    (tmp_path / "server.port").write_text("9876")

    svc = ChatService(db)
    original = mcp_module._service_factory
    mcp_module.set_service_factory(lambda: svc)
    try:
        with patch(
            "chatnut.mcp.get_cached_version_info",
            return_value=VersionInfo(current="0.2.0", latest=None),
        ):
            result = mcp_module.ping()
        assert result["web_url"] == "http://127.0.0.1:9876"
    finally:
        mcp_module.set_service_factory(original)


def test_ping_omits_web_url_when_no_port_file(db, tmp_path, monkeypatch):
    """ping() omits web_url when server.port file is missing."""
    from unittest.mock import patch
    from chatnut import mcp as mcp_module
    from chatnut.service import ChatService
    from chatnut.version_check import VersionInfo

    monkeypatch.setenv("CHATNUT_RUN_DIR", str(tmp_path))

    svc = ChatService(db)
    original = mcp_module._service_factory
    mcp_module.set_service_factory(lambda: svc)
    try:
        with patch(
            "chatnut.mcp.get_cached_version_info",
            return_value=VersionInfo(current="0.2.0", latest=None),
        ):
            result = mcp_module.ping()
        assert "web_url" not in result
    finally:
        mcp_module.set_service_factory(original)


def test_init_room_includes_web_url_and_opens_browser(db, tmp_path, monkeypatch):
    """init_room() includes web_url and auto-opens browser when port file exists."""
    from unittest.mock import patch
    from chatnut import mcp as mcp_module
    from chatnut.service import ChatService

    monkeypatch.setenv("CHATNUT_RUN_DIR", str(tmp_path))
    monkeypatch.setenv("CHATNUT_OPEN_BROWSER", "1")  # re-enable for this test
    (tmp_path / "server.port").write_text("4321")

    svc = ChatService(db)
    original = mcp_module._service_factory
    mcp_module.set_service_factory(lambda: svc)
    try:
        with patch("webbrowser.open") as mock_browser:
            result = mcp_module.init_room("test-proj", "test-room")
        assert result["web_url"] == f"http://127.0.0.1:4321/?room={result['id']}"
        mock_browser.assert_called_once_with(result["web_url"])
    finally:
        mcp_module.set_service_factory(original)


def test_init_room_no_browser_when_no_port_file(db, tmp_path, monkeypatch):
    """init_room() omits web_url and does not open browser when port file is missing."""
    from unittest.mock import patch
    from chatnut import mcp as mcp_module
    from chatnut.service import ChatService

    monkeypatch.setenv("CHATNUT_RUN_DIR", str(tmp_path))

    svc = ChatService(db)
    original = mcp_module._service_factory
    mcp_module.set_service_factory(lambda: svc)
    try:
        with patch("webbrowser.open") as mock_browser:
            result = mcp_module.init_room("test-proj", "test-room-2")
        assert "web_url" not in result
        mock_browser.assert_not_called()
    finally:
        mcp_module.set_service_factory(original)


def test_ping_version_no_update(db):
    from unittest.mock import patch
    from chatnut import mcp as mcp_module
    from chatnut.service import ChatService
    from chatnut.version_check import VersionInfo

    svc = ChatService(db)
    original = mcp_module._service_factory
    mcp_module.set_service_factory(lambda: svc)
    try:
        with patch(
            "chatnut.mcp.get_cached_version_info",
            return_value=VersionInfo(current="0.3.0", latest="0.3.0"),
        ):
            result = mcp_module.ping()
        assert result["version"] == "0.3.0"
        assert "latest" not in result
        assert "update_available" not in result
    finally:
        mcp_module.set_service_factory(original)
