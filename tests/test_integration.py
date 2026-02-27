"""Integration tests — verify full tool flows end-to-end via ChatService."""

import pytest
from team_chat_mcp.service import ChatService


def test_full_lifecycle(db):
    """Room creation -> post messages -> read -> archive -> reject post."""
    svc = ChatService(db)

    # Create room
    room = svc.init_room("integration-test")
    assert room["status"] == "live"

    # Post messages
    m1 = svc.post_message("integration-test", "alice", "hello")
    m2 = svc.post_message("integration-test", "bob", "world")

    # Read all
    result = svc.read_messages("integration-test")
    assert len(result["messages"]) == 2

    # Read incremental
    result = svc.read_messages("integration-test", since_id=m1["id"])
    assert len(result["messages"]) == 1
    assert result["messages"][0]["sender"] == "bob"

    # Archive
    archived = svc.archive_room("integration-test")
    assert archived["archived_at"] is not None

    # Verify post to archived room fails
    with pytest.raises(ValueError, match="archived"):
        svc.post_message("integration-test", "alice", "should fail")

    # Messages still readable after archive
    result = svc.read_messages("integration-test")
    assert len(result["messages"]) == 2


def test_auto_create_room_on_post(db):
    """post_message should auto-create room if it doesn't exist."""
    svc = ChatService(db)
    svc.post_message("auto-room", "alice", "first message")

    rooms = svc.list_rooms()
    names = [r["name"] for r in rooms["rooms"]]
    assert "auto-room" in names


def test_clear_room_preserves_room(db):
    """clear_room deletes messages but keeps the room record."""
    svc = ChatService(db)
    svc.post_message("clear-test", "alice", "hello")
    svc.post_message("clear-test", "bob", "world")

    result = svc.clear_room("clear-test")
    assert result["deleted_count"] == 2

    # Room still exists
    rooms = svc.list_rooms()
    names = [r["name"] for r in rooms["rooms"]]
    assert "clear-test" in names

    # No messages remain
    msgs = svc.read_messages("clear-test")
    assert len(msgs["messages"]) == 0
