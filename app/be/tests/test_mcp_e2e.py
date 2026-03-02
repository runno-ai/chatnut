"""End-to-end tests invoking MCP tools through the FastMCP protocol layer.

Uses fastmcp.Client for in-process MCP dispatch — exercises the full tool-handler
layer (tool registration -> handler -> service -> DB) without HTTP overhead.

API notes discovered during implementation:
- fastmcp.Client wraps CallToolResult: use result.is_error (snake_case, not isError)
- Default raise_on_error=True raises fastmcp.exceptions.ToolError on tool errors;
  error-path tests must pass raise_on_error=False to inspect result.is_error
- result.content[0].text contains JSON-serialised tool output
- result.data contains the parsed dict directly (alternative to json.loads)
"""

import asyncio
import json

import pytest
from fastmcp import Client

from agents_chat_mcp import mcp as mcp_module
from agents_chat_mcp.service import ChatService


@pytest.fixture
async def mcp_svc(db):
    """Wire MCP module to an in-memory ChatService for E2E tests."""
    svc = ChatService(db)
    original_factory = mcp_module._service_factory
    mcp_module.set_service_factory(lambda: svc)
    # Required for wait_for_messages notification path to work in tests
    mcp_module.set_event_loop(asyncio.get_running_loop())
    yield svc
    mcp_module.set_service_factory(original_factory)
    mcp_module.set_event_loop(None)
    if hasattr(mcp_module, "_waiters"):
        mcp_module._waiters.clear()


async def call(client, tool: str, args: dict | None = None):
    """Call a tool and return the parsed dict response."""
    result = await client.call_tool(tool, args or {})
    return json.loads(result.content[0].text)


@pytest.mark.anyio
async def test_e2e_ping(mcp_svc):
    async with Client(mcp_module.mcp) as client:
        data = await call(client, "ping")
    assert data["status"] == "ok"
    assert "db_path" in data


@pytest.mark.anyio
async def test_e2e_init_room(mcp_svc):
    async with Client(mcp_module.mcp) as client:
        room = await call(client, "init_room", {"project": "test", "name": "general"})
    assert room["name"] == "general"
    assert room["project"] == "test"
    assert "id" in room


@pytest.mark.anyio
async def test_e2e_init_room_idempotent(mcp_svc):
    async with Client(mcp_module.mcp) as client:
        r1 = await call(client, "init_room", {"project": "test", "name": "general"})
        r2 = await call(client, "init_room", {"project": "test", "name": "general"})
    assert r1["id"] == r2["id"]


@pytest.mark.anyio
async def test_e2e_init_room_with_branch_and_description(mcp_svc):
    async with Client(mcp_module.mcp) as client:
        room = await call(
            client,
            "init_room",
            {"project": "test", "name": "feature", "branch": "feat/x", "description": "Feature room"},
        )
    assert room["branch"] == "feat/x"
    assert room["description"] == "Feature room"


@pytest.mark.anyio
async def test_e2e_post_and_read_messages(mcp_svc):
    async with Client(mcp_module.mcp) as client:
        room = await call(client, "init_room", {"project": "test", "name": "chat"})
        room_id = room["id"]
        await call(client, "post_message", {"room_id": room_id, "sender": "alice", "content": "hello"})
        await call(client, "post_message", {"room_id": room_id, "sender": "bob", "content": "world"})
        result = await call(client, "read_messages", {"room_id": room_id})
    assert len(result["messages"]) == 2
    assert result["messages"][0]["sender"] == "alice"
    assert result["messages"][1]["sender"] == "bob"


@pytest.mark.anyio
async def test_e2e_read_messages_since_id(mcp_svc):
    async with Client(mcp_module.mcp) as client:
        room = await call(client, "init_room", {"project": "test", "name": "chat"})
        room_id = room["id"]
        m1 = await call(client, "post_message", {"room_id": room_id, "sender": "alice", "content": "first"})
        await call(client, "post_message", {"room_id": room_id, "sender": "bob", "content": "second"})
        result = await call(client, "read_messages", {"room_id": room_id, "since_id": m1["id"]})
    assert len(result["messages"]) == 1
    assert result["messages"][0]["content"] == "second"


@pytest.mark.anyio
async def test_e2e_post_message_system_type(mcp_svc):
    async with Client(mcp_module.mcp) as client:
        room = await call(client, "init_room", {"project": "test", "name": "chat"})
        msg = await call(
            client,
            "post_message",
            {"room_id": room["id"], "sender": "system", "content": "Room created", "message_type": "system"},
        )
    assert msg["message_type"] == "system"


@pytest.mark.anyio
async def test_e2e_list_rooms(mcp_svc):
    async with Client(mcp_module.mcp) as client:
        await call(client, "init_room", {"project": "proj-a", "name": "general"})
        await call(client, "init_room", {"project": "proj-b", "name": "general"})
        result = await call(client, "list_rooms", {})
    assert len(result["rooms"]) == 2


@pytest.mark.anyio
async def test_e2e_list_rooms_filter_by_project(mcp_svc):
    async with Client(mcp_module.mcp) as client:
        await call(client, "init_room", {"project": "proj-a", "name": "r1"})
        await call(client, "init_room", {"project": "proj-b", "name": "r2"})
        result = await call(client, "list_rooms", {"project": "proj-a"})
    assert len(result["rooms"]) == 1
    assert result["rooms"][0]["project"] == "proj-a"


@pytest.mark.anyio
async def test_e2e_list_rooms_filter_archived(mcp_svc):
    async with Client(mcp_module.mcp) as client:
        await call(client, "init_room", {"project": "proj", "name": "live-room"})
        await call(client, "init_room", {"project": "proj", "name": "arch-room"})
        await call(client, "archive_room", {"project": "proj", "name": "arch-room"})
        live_result = await call(client, "list_rooms", {"status": "live"})
        arch_result = await call(client, "list_rooms", {"status": "archived"})
        all_result = await call(client, "list_rooms", {"status": "all"})
    assert len(live_result["rooms"]) == 1
    assert live_result["rooms"][0]["name"] == "live-room"
    assert len(arch_result["rooms"]) == 1
    assert arch_result["rooms"][0]["name"] == "arch-room"
    assert len(all_result["rooms"]) == 2


@pytest.mark.anyio
async def test_e2e_list_projects(mcp_svc):
    async with Client(mcp_module.mcp) as client:
        await call(client, "init_room", {"project": "alpha", "name": "r"})
        await call(client, "init_room", {"project": "beta", "name": "r"})
        result = await call(client, "list_projects", {})
    assert set(result["projects"]) == {"alpha", "beta"}


@pytest.mark.anyio
async def test_e2e_archive_room(mcp_svc):
    async with Client(mcp_module.mcp) as client:
        await call(client, "init_room", {"project": "proj", "name": "dev"})
        result = await call(client, "archive_room", {"project": "proj", "name": "dev"})
    assert result["archived_at"] is not None
    assert result["name"] == "dev"
    assert result["project"] == "proj"


@pytest.mark.anyio
async def test_e2e_delete_room(mcp_svc):
    async with Client(mcp_module.mcp) as client:
        room = await call(client, "init_room", {"project": "proj", "name": "dev"})
        await call(client, "archive_room", {"project": "proj", "name": "dev"})
        result = await call(client, "delete_room", {"room_id": room["id"]})
    assert "deleted_messages" in result


@pytest.mark.anyio
async def test_e2e_clear_room(mcp_svc):
    async with Client(mcp_module.mcp) as client:
        room = await call(client, "init_room", {"project": "proj", "name": "dev"})
        room_id = room["id"]
        await call(client, "post_message", {"room_id": room_id, "sender": "alice", "content": "msg"})
        await call(client, "clear_room", {"project": "proj", "name": "dev"})
        result = await call(client, "read_messages", {"room_id": room_id})
    assert result["messages"] == []


@pytest.mark.anyio
async def test_e2e_mark_read(mcp_svc):
    async with Client(mcp_module.mcp) as client:
        room = await call(client, "init_room", {"project": "proj", "name": "dev"})
        room_id = room["id"]
        msg = await call(client, "post_message", {"room_id": room_id, "sender": "alice", "content": "hi"})
        result = await call(
            client,
            "mark_read",
            {"room_id": room_id, "reader": "bob", "last_read_message_id": msg["id"]},
        )
    assert result["last_read_message_id"] == msg["id"]
    assert result["reader"] == "bob"


@pytest.mark.anyio
async def test_e2e_mark_read_cursor_forward_only(mcp_svc):
    """mark_read() should not allow the cursor to move backward."""
    async with Client(mcp_module.mcp) as client:
        room = await call(client, "init_room", {"project": "proj", "name": "dev"})
        room_id = room["id"]
        m1 = await call(client, "post_message", {"room_id": room_id, "sender": "alice", "content": "first"})
        m2 = await call(client, "post_message", {"room_id": room_id, "sender": "alice", "content": "second"})
        # Mark up to m2
        await call(client, "mark_read", {"room_id": room_id, "reader": "bob", "last_read_message_id": m2["id"]})
        # Try to move cursor back to m1
        result = await call(
            client,
            "mark_read",
            {"room_id": room_id, "reader": "bob", "last_read_message_id": m1["id"]},
        )
    # Cursor should stay at m2 (forward-only)
    assert result["last_read_message_id"] == m2["id"]


@pytest.mark.anyio
async def test_e2e_search(mcp_svc):
    async with Client(mcp_module.mcp) as client:
        room = await call(client, "init_room", {"project": "proj", "name": "auth-discussion"})
        await call(
            client,
            "post_message",
            {"room_id": room["id"], "sender": "alice", "content": "implement oauth flow"},
        )
        result = await call(client, "search", {"query": "oauth"})
    assert len(result["message_rooms"]) >= 1


@pytest.mark.anyio
async def test_e2e_search_by_room_name(mcp_svc):
    async with Client(mcp_module.mcp) as client:
        await call(client, "init_room", {"project": "proj", "name": "auth-discussion"})
        await call(client, "init_room", {"project": "proj", "name": "general"})
        result = await call(client, "search", {"query": "auth"})
    room_names = [r["name"] for r in result["rooms"]]
    assert "auth-discussion" in room_names


@pytest.mark.anyio
async def test_e2e_search_filter_by_project(mcp_svc):
    async with Client(mcp_module.mcp) as client:
        room_a = await call(client, "init_room", {"project": "proj-a", "name": "dev"})
        room_b = await call(client, "init_room", {"project": "proj-b", "name": "dev"})
        await call(
            client,
            "post_message",
            {"room_id": room_a["id"], "sender": "alice", "content": "oauth in proj-a"},
        )
        await call(
            client,
            "post_message",
            {"room_id": room_b["id"], "sender": "bob", "content": "oauth in proj-b"},
        )
        result = await call(client, "search", {"query": "oauth", "project": "proj-a"})
    # Only room_a should match when filtering by proj-a
    # message_rooms contains {room_id, match_count} entries
    matched_room_ids = {r["room_id"] for r in result["message_rooms"]}
    assert room_a["id"] in matched_room_ids
    assert room_b["id"] not in matched_room_ids


@pytest.mark.anyio
async def test_e2e_wait_for_messages(mcp_svc):
    """wait_for_messages() returns when a new message is posted concurrently."""
    async with Client(mcp_module.mcp) as client:
        room = await call(client, "init_room", {"project": "proj", "name": "waitroom"})
        room_id = room["id"]
        msg0 = await call(client, "post_message", {"room_id": room_id, "sender": "alice", "content": "seed"})
        since_id = msg0["id"]

        async def post_delayed():
            await asyncio.sleep(0.3)
            await call(client, "post_message", {"room_id": room_id, "sender": "bob", "content": "new"})

        task = asyncio.create_task(post_delayed())
        result = await call(
            client,
            "wait_for_messages",
            {"room_id": room_id, "since_id": since_id, "timeout": 10},
        )
        await task

    assert result["timed_out"] is False
    assert len(result["messages"]) >= 1
    assert result["messages"][0]["content"] == "new"


@pytest.mark.anyio
async def test_e2e_wait_for_messages_timeout(mcp_svc):
    """wait_for_messages() returns timed_out=True when no messages arrive."""
    async with Client(mcp_module.mcp) as client:
        room = await call(client, "init_room", {"project": "proj", "name": "emptyroom"})
        room_id = room["id"]
        msg0 = await call(client, "post_message", {"room_id": room_id, "sender": "alice", "content": "seed"})
        result = await call(
            client,
            "wait_for_messages",
            {"room_id": room_id, "since_id": msg0["id"], "timeout": 0.1},
        )
    assert result["timed_out"] is True
    assert result["messages"] == []


@pytest.mark.anyio
async def test_e2e_wait_for_messages_early_exit(mcp_svc):
    """wait_for_messages() returns immediately when messages already exist after since_id."""
    async with Client(mcp_module.mcp) as client:
        room = await call(client, "init_room", {"project": "proj", "name": "preloaded"})
        room_id = room["id"]
        m0 = await call(client, "post_message", {"room_id": room_id, "sender": "alice", "content": "first"})
        await call(client, "post_message", {"room_id": room_id, "sender": "bob", "content": "second"})
        # since_id=m0["id"] means "after m0" — second message already exists
        result = await call(
            client,
            "wait_for_messages",
            {"room_id": room_id, "since_id": m0["id"], "timeout": 30},
        )
    assert result["timed_out"] is False
    assert len(result["messages"]) == 1
    assert result["messages"][0]["content"] == "second"


# --- Error path tests (raise_on_error=False to inspect is_error) ---

@pytest.mark.anyio
async def test_e2e_post_message_invalid_room(mcp_svc):
    """post_message() to a non-existent room_id should return an MCP error."""
    async with Client(mcp_module.mcp) as client:
        result = await client.call_tool(
            "post_message",
            {"room_id": "00000000-0000-0000-0000-000000000000", "sender": "x", "content": "y"},
            raise_on_error=False,
        )
    assert result.is_error is True


@pytest.mark.anyio
async def test_e2e_search_empty_query_error(mcp_svc):
    """search() with empty query should return an MCP error."""
    async with Client(mcp_module.mcp) as client:
        result = await client.call_tool("search", {"query": ""}, raise_on_error=False)
    assert result.is_error is True


@pytest.mark.anyio
async def test_e2e_delete_live_room_error(mcp_svc):
    """delete_room() on a live (non-archived) room should return an MCP error."""
    async with Client(mcp_module.mcp) as client:
        room = await call(client, "init_room", {"project": "proj", "name": "live"})
        result = await client.call_tool(
            "delete_room", {"room_id": room["id"]}, raise_on_error=False
        )
    assert result.is_error is True


@pytest.mark.anyio
async def test_e2e_wait_for_messages_invalid_room_error(mcp_svc):
    """wait_for_messages() with an unknown room_id should return an MCP error."""
    async with Client(mcp_module.mcp) as client:
        result = await client.call_tool(
            "wait_for_messages",
            {"room_id": "00000000-0000-0000-0000-000000000000", "since_id": 0, "timeout": 1},
            raise_on_error=False,
        )
    assert result.is_error is True


@pytest.mark.anyio
async def test_e2e_read_messages_type_filter(mcp_svc):
    """read_messages() with message_type filter returns only matching messages."""
    async with Client(mcp_module.mcp) as client:
        room = await call(client, "init_room", {"project": "proj", "name": "mixed"})
        room_id = room["id"]
        await call(client, "post_message", {"room_id": room_id, "sender": "alice", "content": "user msg"})
        await call(
            client,
            "post_message",
            {"room_id": room_id, "sender": "system", "content": "sys msg", "message_type": "system"},
        )
        user_result = await call(client, "read_messages", {"room_id": room_id, "message_type": "message"})
        sys_result = await call(client, "read_messages", {"room_id": room_id, "message_type": "system"})
    assert all(m["message_type"] == "message" for m in user_result["messages"])
    assert all(m["message_type"] == "system" for m in sys_result["messages"])
    assert len(user_result["messages"]) == 1
    assert len(sys_result["messages"]) == 1
