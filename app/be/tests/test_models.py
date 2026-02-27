"""Tests for Room and Message dataclasses."""

from team_chat_mcp.models import Room, Message


def test_room_to_dict():
    room = Room(
        id="abc-123",
        name="dev",
        project="team-chat-mcp",
        branch="main",
        description="Development room",
        status="live",
        created_at="2026-01-01T00:00:00+00:00",
        archived_at=None,
        metadata=None,
    )
    d = room.to_dict()
    assert d["id"] == "abc-123"
    assert d["name"] == "dev"
    assert d["project"] == "team-chat-mcp"
    assert d["branch"] == "main"
    assert d["description"] == "Development room"
    assert d["status"] == "live"
    assert d["archived_at"] is None
    assert d["metadata"] is None


def test_room_to_dict_minimal():
    room = Room(
        id="abc-123",
        name="dev",
        project="my-project",
        branch=None,
        description=None,
        status="live",
        created_at="2026-01-01T00:00:00+00:00",
        archived_at=None,
        metadata=None,
    )
    d = room.to_dict()
    assert d["branch"] is None
    assert d["description"] is None


def test_message_to_dict():
    msg = Message(
        id=1,
        room_id="abc-123",
        sender="alice",
        content="hello",
        message_type="message",
        created_at="2026-01-01T00:00:00+00:00",
        metadata=None,
    )
    d = msg.to_dict()
    assert d["id"] == 1
    assert d["room_id"] == "abc-123"
    assert d["sender"] == "alice"
    assert d["content"] == "hello"
    assert d["message_type"] == "message"
    assert d["metadata"] is None


def test_message_system_type():
    msg = Message(
        id=2,
        room_id="abc-123",
        sender="system",
        content="Room created",
        message_type="system",
        created_at="2026-01-01T00:00:00+00:00",
        metadata='{"event": "room_created"}',
    )
    d = msg.to_dict()
    assert d["message_type"] == "system"
    assert d["metadata"] == '{"event": "room_created"}'
