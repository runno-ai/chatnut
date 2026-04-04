# tests/test_routes.py
"""Tests for REST + SSE endpoints."""

import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from chatnut.service import ChatService
from chatnut.routes import create_router, chatroom_event_generator, message_event_generator, status_event_generator


@pytest.fixture
def svc(db):
    """ChatService backed by in-memory DB."""
    return ChatService(db)


@pytest.fixture
def app(db, svc, tmp_path):
    """FastAPI test app with routes + SPA handler wired to in-memory DB."""
    import os
    from fastapi.responses import FileResponse, JSONResponse

    test_app = FastAPI()
    router = create_router(lambda: svc)
    test_app.include_router(router)

    # Mount a SPA catch-all that mirrors app.py's serve_spa with path traversal guard
    static_dir = str(tmp_path)

    @test_app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        abs_static = os.path.abspath(static_dir)
        file_path = os.path.normpath(os.path.join(abs_static, full_path))
        if not file_path.startswith(abs_static):
            return JSONResponse(status_code=404, content={"error": "Not found"})
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        index_path = os.path.join(abs_static, "index.html")
        if os.path.isfile(index_path):
            return FileResponse(index_path)
        return JSONResponse(status_code=503, content={"error": "Frontend not built"})

    return test_app


@pytest.fixture
def client(app):
    return TestClient(app)


def test_status(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_projects_empty(client):
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    assert resp.json()["projects"] == []


def test_projects_with_rooms(client, db):
    svc = ChatService(db)
    svc.init_room("proj-a", "dev")
    svc.init_room("proj-b", "staging")
    resp = client.get("/api/projects")
    assert set(resp.json()["projects"]) == {"proj-a", "proj-b"}


def test_chatrooms_list(client, db):
    svc = ChatService(db)
    svc.init_room("proj", "dev")
    svc.init_room("proj", "staging")
    resp = client.get("/api/chatrooms", params={"project": "proj"})
    assert resp.status_code == 200
    assert len(resp.json()["rooms"]) == 2


def test_chatrooms_filter_by_branch(client, db):
    svc = ChatService(db)
    svc.init_room("proj", "dev", branch="main")
    svc.init_room("proj", "staging", branch="feat/auth")
    resp = client.get("/api/chatrooms", params={"project": "proj", "branch": "main"})
    rooms = resp.json()["rooms"]
    assert len(rooms) == 1
    assert rooms[0]["name"] == "dev"


def test_room_messages(client, db):
    svc = ChatService(db)
    svc.init_room("proj", "dev")
    svc.post_message("proj", "dev", "alice", "hello")
    svc.post_message("proj", "dev", "bob", "world")
    rooms = svc.list_rooms(project="proj")
    room_id = rooms["rooms"][0]["id"]
    resp = client.get(f"/api/chatrooms/{room_id}/messages")
    assert resp.status_code == 200
    msgs = resp.json()["messages"]
    assert len(msgs) == 2
    assert msgs[0]["sender"] == "alice"


def test_room_messages_since_id(client, db):
    svc = ChatService(db)
    svc.init_room("proj", "dev")
    m1 = svc.post_message("proj", "dev", "alice", "first")
    svc.post_message("proj", "dev", "bob", "second")
    rooms = svc.list_rooms(project="proj")
    room_id = rooms["rooms"][0]["id"]
    resp = client.get(f"/api/chatrooms/{room_id}/messages", params={"since_id": m1["id"]})
    msgs = resp.json()["messages"]
    assert len(msgs) == 1
    assert msgs[0]["content"] == "second"


def test_delete_chatroom(client, db):
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    svc.archive_room("proj", "dev")
    resp = client.delete(f"/api/chatrooms/{room['id']}")
    assert resp.status_code == 200
    assert resp.json()["deleted_messages"] == 0


def test_delete_live_chatroom_returns_422(client, db):
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    resp = client.delete(f"/api/chatrooms/{room['id']}")
    assert resp.status_code == 422


def test_delete_nonexistent_chatroom_returns_404(client):
    resp = client.delete("/api/chatrooms/nonexistent-id")
    assert resp.status_code == 404


def test_search(client, db):
    svc = ChatService(db)
    svc.init_room("proj", "planning")
    svc.post_message("proj", "planning", "alice", "discuss auth feature")
    resp = client.get("/api/search", params={"q": "auth", "project": "proj"})
    assert resp.status_code == 200
    assert len(resp.json()["message_rooms"]) == 1


@pytest.mark.anyio
async def test_stream_messages_initial_history(db):
    """Test SSE message generator sends full history when last_id=0.

    Directly invokes the extracted async generator to avoid ASGI test client
    SSE buffering issues (TestClient blocks on infinite SSE streams).
    """
    from chatnut.routes import message_event_generator

    svc = ChatService(db)
    svc.init_room("proj", "dev")
    svc.post_message("proj", "dev", "alice", "hello")
    svc.post_message("proj", "dev", "bob", "world")
    rooms = svc.list_rooms(project="proj")
    room_id = rooms["rooms"][0]["id"]

    # Use is_disconnected that returns True after initial history is sent
    # (the generator yields history before entering the poll loop)
    call_count = 0

    async def disconnect_after_history():
        nonlocal call_count
        call_count += 1
        return True  # Disconnect immediately on first poll check

    events = []
    async for event in message_event_generator(
        svc, room_id, last_id=0, is_disconnected=disconnect_after_history
    ):
        events.append(event)

    # Should have received both messages as initial history
    assert len(events) == 2
    msg0 = json.loads(events[0]["data"])
    msg1 = json.loads(events[1]["data"])
    assert msg0["sender"] == "alice"
    assert msg1["sender"] == "bob"
    # Events should have id fields for SSE reconnection
    assert "id" in events[0]
    assert "id" in events[1]


@pytest.mark.anyio
async def test_stream_messages_last_event_id(db):
    """Test SSE message generator honors last_id for reconnection.

    When last_id > 0, the generator skips initial history and only
    sends messages after the given ID (simulating Last-Event-Id header).
    """
    from chatnut.routes import message_event_generator

    svc = ChatService(db)
    svc.init_room("proj", "dev")
    m1 = svc.post_message("proj", "dev", "alice", "first")
    m2 = svc.post_message("proj", "dev", "bob", "second")
    rooms = svc.list_rooms(project="proj")
    room_id = rooms["rooms"][0]["id"]

    # Disconnect after first poll iteration
    poll_count = 0

    async def disconnect_after_one_poll():
        nonlocal poll_count
        poll_count += 1
        # Allow first poll to run (which finds the new message), disconnect on second
        return poll_count > 1

    events = []
    async for event in message_event_generator(
        svc, room_id, last_id=m1["id"], is_disconnected=disconnect_after_one_poll
    ):
        if "data" in event:
            events.append(event)

    # Should only receive the second message (after m1's id)
    assert len(events) == 1
    msg = json.loads(events[0]["data"])
    assert msg["content"] == "second"


# --- Test 3: chatroom_event_generator ---


@pytest.mark.anyio
async def test_chatroom_event_generator_initial_emission(db):
    """Test SSE chatroom generator emits room data with stats on first iteration."""
    from chatnut.routes import chatroom_event_generator

    svc = ChatService(db)
    svc.init_room("proj", "dev")
    svc.post_message("proj", "dev", "alice", "hello")
    svc.post_message("proj", "dev", "bob", "world")

    # The is_disconnected check runs at the top of the loop, so we must allow
    # the first iteration to proceed (return False) then disconnect on the second.
    call_count = 0

    async def disconnect_after_first_yield():
        nonlocal call_count
        call_count += 1
        return call_count > 1

    events = []
    async for event in chatroom_event_generator(
        svc, project="proj", is_disconnected=disconnect_after_first_yield
    ):
        events.append(event)

    assert len(events) == 1
    payload = json.loads(events[0]["data"])
    assert "active" in payload
    assert "archived" in payload
    # The room should have stats enriched
    active_rooms = payload["active"]
    assert len(active_rooms) == 1
    room = active_rooms[0]
    assert room["name"] == "dev"
    assert room["messageCount"] == 2
    assert room["roleCounts"]["alice"] == 1
    assert room["roleCounts"]["bob"] == 1


@pytest.mark.anyio
async def test_chatroom_event_generator_no_reemit_unchanged(db):
    """Test SSE chatroom generator does not re-emit when data is unchanged (hash dedup)."""
    from chatnut.routes import chatroom_event_generator

    svc = ChatService(db)
    svc.init_room("proj", "dev")

    poll_count = 0

    async def disconnect_after_three_polls():
        nonlocal poll_count
        poll_count += 1
        # Let the generator run three times:
        # 1st: pass, emit data (new hash)
        # 2nd: pass, no emit (same hash)
        # 3rd: disconnect
        return poll_count > 3

    events = []
    async for event in chatroom_event_generator(
        svc, project="proj", is_disconnected=disconnect_after_three_polls
    ):
        events.append(event)

    # Only one data event should be emitted (subsequent polls have identical hash)
    data_events = [e for e in events if "data" in e]
    assert len(data_events) == 1


# --- Test 6: SPA path traversal security ---


def test_spa_path_traversal_returns_404(client):
    """Path traversal attempts should return 404, not file content.

    Tests both explicit traversal (../../etc/passwd) and normalized traversal
    that resolves outside the static directory.
    """
    resp = client.get("/../../etc/passwd")
    assert resp.status_code in (404, 503)  # 404 if traversal blocked, 503 if no index.html


def test_spa_serves_static_file(tmp_path, db, svc):
    """SPA handler should serve an existing static file."""
    import os
    from fastapi.responses import FileResponse, JSONResponse

    # Create a real static file in tmp_path
    js_file = tmp_path / "app.js"
    js_file.write_text("console.log('hello');")

    test_app = FastAPI()
    router = create_router(lambda: svc)
    test_app.include_router(router)
    static_dir = str(tmp_path)

    @test_app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        abs_static = os.path.abspath(static_dir)
        file_path = os.path.normpath(os.path.join(abs_static, full_path))
        if not file_path.startswith(abs_static):
            return JSONResponse(status_code=404, content={"error": "Not found"})
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        index_path = os.path.join(abs_static, "index.html")
        if os.path.isfile(index_path):
            return FileResponse(index_path)
        return JSONResponse(status_code=503, content={"error": "Frontend not built"})

    tc = TestClient(test_app)
    resp = tc.get("/app.js")
    assert resp.status_code == 200
    assert "console.log" in resp.text


def test_spa_api_routes_unaffected(client):
    """API routes should still work normally alongside the SPA catch-all."""
    resp = client.get("/api/status")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# --- Test 7: Invalid status and Last-Event-Id HTTP tests ---


def test_chatrooms_invalid_status_returns_422(client):
    """GET /api/chatrooms?status=bogus should return 422."""
    resp = client.get("/api/chatrooms", params={"status": "bogus"})
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_stream_messages_non_integer_last_event_id(db):
    """Non-integer Last-Event-Id should fall back to 0, sending full history.

    Tests the route's try/except around int(last_event_id) by simulating
    the same logic the route uses: parse the header, fall back to 0 on failure,
    then verify the generator works correctly with last_id=0.
    """
    from chatnut.routes import message_event_generator

    svc = ChatService(db)
    svc.init_room("proj", "dev")
    svc.post_message("proj", "dev", "alice", "hello")
    rooms = svc.list_rooms(project="proj")
    room_id = rooms["rooms"][0]["id"]

    # Simulate the route's Last-Event-Id parsing
    last_event_id = "not-a-number"
    try:
        last_id = int(last_event_id)
    except (ValueError, TypeError):
        last_id = 0

    assert last_id == 0  # Confirm fallback

    # Verify the generator works with the fallen-back value
    call_count = 0

    async def disconnect_after_history():
        nonlocal call_count
        call_count += 1
        return True

    events = []
    async for event in message_event_generator(
        svc, room_id, last_id=last_id, is_disconnected=disconnect_after_history
    ):
        events.append(event)

    # Should receive the message as initial history (last_id=0 sends everything)
    assert len(events) == 1
    msg = json.loads(events[0]["data"])
    assert msg["sender"] == "alice"


# --- Task 4: mark_read endpoint + SSE unread enrichment ---


def test_mark_read_endpoint(client, svc):
    room = svc.init_room("proj", "dev")
    msg = svc.post_message("proj", "dev", "alice", "hello")
    resp = client.post(
        f"/api/chatrooms/{room['id']}/read",
        json={"reader": "web-user", "last_read_message_id": msg["id"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["reader"] == "web-user"
    assert data["last_read_message_id"] == msg["id"]


def test_mark_read_nonexistent_room(client):
    resp = client.post(
        "/api/chatrooms/nonexistent/read",
        json={"reader": "web-user", "last_read_message_id": 1},
    )
    assert resp.status_code == 404


def test_mark_read_empty_reader_returns_422(client, svc):
    room = svc.init_room("proj", "dev")
    svc.post_message("proj", "dev", "alice", "hello")
    resp = client.post(
        f"/api/chatrooms/{room['id']}/read",
        json={"reader": "   ", "last_read_message_id": 1},
    )
    assert resp.status_code == 422


def test_mark_read_negative_cursor_returns_422(client, svc):
    room = svc.init_room("proj", "dev")
    svc.post_message("proj", "dev", "alice", "hello")
    resp = client.post(
        f"/api/chatrooms/{room['id']}/read",
        json={"reader": "web-user", "last_read_message_id": -1},
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_chatroom_sse_includes_unread_count(db):
    """SSE chatroom stream includes unreadCount when reader param is present."""
    svc = ChatService(db)
    svc.init_room("proj", "dev")
    svc.post_message("proj", "dev", "alice", "msg1")
    svc.post_message("proj", "dev", "alice", "msg2")

    gen = chatroom_event_generator(svc, reader="web-user")
    event = await gen.__anext__()
    rooms = json.loads(event["data"])
    active = rooms["active"]
    assert len(active) == 1
    assert active[0]["unreadCount"] == 2  # web-user hasn't read anything
    await gen.aclose()


def test_status_includes_version(client):
    from unittest.mock import patch
    from chatnut.version_check import VersionInfo

    with patch(
        "chatnut.routes.get_cached_version_info",
        return_value=VersionInfo(current="0.2.0", latest="0.3.0"),
    ):
        resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["version"] == "0.2.0"
    assert data["latest"] == "0.3.0"
    assert data["update_available"] is True


def test_status_no_update(client):
    from unittest.mock import patch
    from chatnut.version_check import VersionInfo

    with patch(
        "chatnut.routes.get_cached_version_info",
        return_value=VersionInfo(current="0.3.0", latest="0.3.0"),
    ):
        resp = client.get("/api/status")
    data = resp.json()
    assert data["version"] == "0.3.0"
    assert "latest" not in data


# --- Task 5: REST + SSE endpoints for room status ---


def test_get_room_status(client, svc):
    """GET /api/chatrooms/{room_id}/status returns statuses for the room."""
    room = svc.init_room("proj", "dev")
    room_id = room["id"]
    svc.update_status(room_id, "alice", "working on auth")
    svc.update_status(room_id, "bob", "reviewing PR")
    resp = client.get(f"/api/chatrooms/{room_id}/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "statuses" in data
    assert len(data["statuses"]) == 2
    senders = {s["sender"] for s in data["statuses"]}
    assert senders == {"alice", "bob"}


def test_get_room_status_nonexistent(client):
    """GET /api/chatrooms/{room_id}/status returns 404 for unknown room."""
    resp = client.get("/api/chatrooms/nonexistent-room-id/status")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_status_event_generator_emits_on_change(db):
    """SSE status generator emits when status changes, deduplicates unchanged."""
    from chatnut.routes import status_event_generator

    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    room_id = room["id"]

    poll_count = 0

    async def disconnect_after_two_polls():
        nonlocal poll_count
        poll_count += 1
        return poll_count > 2

    # No statuses yet — first emission should still emit (new hash)
    events = []
    async for event in status_event_generator(
        svc, room_id, is_disconnected=disconnect_after_two_polls
    ):
        events.append(event)

    # First iteration emits data (new hash), second iteration does not (same hash)
    data_events = [e for e in events if "data" in e]
    assert len(data_events) == 1
    payload = json.loads(data_events[0]["data"])
    assert "statuses" in payload
    assert payload["statuses"] == []


@pytest.mark.anyio
async def test_status_event_generator_emits_on_status_update(db):
    """SSE status generator detects new statuses and emits updated data."""
    from chatnut.routes import status_event_generator

    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    room_id = room["id"]
    svc.update_status(room_id, "alice", "working")

    call_count = 0

    async def disconnect_after_first():
        nonlocal call_count
        call_count += 1
        return call_count > 1

    events = []
    async for event in status_event_generator(
        svc, room_id, is_disconnected=disconnect_after_first
    ):
        events.append(event)

    data_events = [e for e in events if "data" in e]
    assert len(data_events) == 1
    payload = json.loads(data_events[0]["data"])
    assert len(payload["statuses"]) == 1
    assert payload["statuses"][0]["sender"] == "alice"
    assert payload["statuses"][0]["status"] == "working"


# --- Per-stream poll intervals ---


def test_poll_intervals_are_per_stream():
    """Each SSE stream type has its own poll interval."""
    from chatnut.routes import MESSAGE_POLL_INTERVAL, STATUS_POLL_INTERVAL, CHATROOM_POLL_INTERVAL
    assert MESSAGE_POLL_INTERVAL <= 1.0, "Messages should poll at ≤1s"
    assert STATUS_POLL_INTERVAL >= 2.0, "Status can poll at ≥2s"
    assert CHATROOM_POLL_INTERVAL >= 2.0, "Chatroom list can poll at ≥2s"


# --- Event-driven notification tests ---


@pytest.mark.anyio
async def test_message_generator_wakes_on_notification(svc):
    """Message generator yields immediately when notified instead of waiting for poll."""
    import asyncio
    import anyio
    from chatnut.notify import set_event_loop, notify

    loop = asyncio.get_running_loop()
    set_event_loop(loop)

    room = svc.init_room("test", "notify-test")
    room_id = room["id"]
    svc.post_message_by_room_id(room_id, "alice", "setup")

    gen = message_event_generator(svc, room_id, last_id=0)
    # Drain initial history
    first = await gen.__anext__()
    assert "setup" in first["data"]

    # Post a message and notify — generator should yield quickly
    svc.post_message_by_room_id(room_id, "bob", "event-driven")
    notify(f"messages:{room_id}")

    with anyio.fail_after(1.0):
        event = await gen.__anext__()
    assert "event-driven" in event["data"]

    await gen.aclose()
    set_event_loop(None)


@pytest.mark.anyio
async def test_status_generator_wakes_on_notification(svc):
    """Status generator yields immediately when notified."""
    import asyncio
    import anyio
    from chatnut.notify import set_event_loop, notify

    loop = asyncio.get_running_loop()
    set_event_loop(loop)

    room = svc.init_room("test", "status-notify-test")
    room_id = room["id"]

    gen = status_event_generator(svc, room_id)
    # Drain initial status
    first = await gen.__anext__()

    # Update status and notify
    svc.update_status(room_id, "alice", "working")
    notify(f"status:{room_id}")

    with anyio.fail_after(1.0):
        event = await gen.__anext__()
    assert "working" in event["data"]

    await gen.aclose()
    set_event_loop(None)
