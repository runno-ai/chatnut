"""Tests for Room and Message dataclasses."""

from team_chat_mcp.models import Room, Message


def test_room_to_dict():
    room = Room(name="dev", status="live", created_at="2026-02-27T10:00:00+00:00", archived_at=None)
    d = room.to_dict()
    assert d == {
        "name": "dev",
        "status": "live",
        "created_at": "2026-02-27T10:00:00+00:00",
        "archived_at": None,
    }


def test_message_to_dict():
    msg = Message(id=1, room="dev", sender="architect", content="hello", created_at="2026-02-27T10:00:00+00:00")
    d = msg.to_dict()
    assert d == {
        "id": 1,
        "room": "dev",
        "sender": "architect",
        "content": "hello",
        "created_at": "2026-02-27T10:00:00+00:00",
    }
