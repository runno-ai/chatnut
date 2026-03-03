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
