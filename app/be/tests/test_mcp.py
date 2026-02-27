"""Smoke tests for MCP tool registration."""

import pytest

from team_chat_mcp.mcp import mcp


@pytest.mark.asyncio
async def test_all_tools_registered():
    """Verify all expected MCP tools are registered."""
    tools = await mcp.list_tools()
    tool_names = {t.name for t in tools}
    expected = {"ping", "init_room", "post_message", "read_messages", "list_rooms", "archive_room", "clear_room", "search", "list_projects"}
    assert expected.issubset(tool_names), f"Missing tools: {expected - tool_names}"
