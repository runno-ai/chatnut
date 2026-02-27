# tests/test_routes.py
"""Tests for REST + SSE endpoints."""

import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from team_chat_mcp.service import ChatService
from team_chat_mcp.routes import create_router


@pytest.fixture
def app(db):
    """FastAPI test app with routes wired to in-memory DB."""
    svc = ChatService(db)
    test_app = FastAPI()
    router = create_router(lambda: svc)
    test_app.include_router(router)
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
    m1 = svc.post_message("proj", "dev", "alice", "first")
    svc.post_message("proj", "dev", "bob", "second")
    rooms = svc.list_rooms(project="proj")
    room_id = rooms["rooms"][0]["id"]
    resp = client.get(f"/api/chatrooms/{room_id}/messages", params={"since_id": m1["id"]})
    msgs = resp.json()["messages"]
    assert len(msgs) == 1
    assert msgs[0]["content"] == "second"


def test_search(client, db):
    svc = ChatService(db)
    svc.post_message("proj", "planning", "alice", "discuss auth feature")
    resp = client.get("/api/search", params={"q": "auth", "project": "proj"})
    assert resp.status_code == 200
    assert len(resp.json()["message_rooms"]) == 1


@pytest.mark.asyncio
async def test_stream_messages_initial_history(db):
    """Test SSE message generator sends full history when last_id=0.

    Directly invokes the extracted async generator to avoid ASGI test client
    SSE buffering issues (TestClient blocks on infinite SSE streams).
    """
    from team_chat_mcp.routes import message_event_generator

    svc = ChatService(db)
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


@pytest.mark.asyncio
async def test_stream_messages_last_event_id(db):
    """Test SSE message generator honors last_id for reconnection.

    When last_id > 0, the generator skips initial history and only
    sends messages after the given ID (simulating Last-Event-Id header).
    """
    from team_chat_mcp.routes import message_event_generator

    svc = ChatService(db)
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
