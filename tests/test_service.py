"""Tests for ChatService business logic."""

import pytest
from team_chat_mcp.service import ChatService


def test_init_room(db):
    svc = ChatService(db)
    result = svc.init_room("dev")
    assert result["name"] == "dev"
    assert result["status"] == "live"
    assert "created_at" in result


def test_init_room_idempotent(db):
    svc = ChatService(db)
    r1 = svc.init_room("dev")
    r2 = svc.init_room("dev")
    assert r1["created_at"] == r2["created_at"]


def test_post_message(db):
    svc = ChatService(db)
    result = svc.post_message("dev", "alice", "hello world")
    assert result["id"] is not None
    assert result["room"] == "dev"
    assert result["sender"] == "alice"
    assert result["content"] == "hello world"
    assert "created_at" in result


def test_post_message_auto_creates_room(db):
    svc = ChatService(db)
    svc.post_message("new-room", "alice", "first message")
    result = svc.list_rooms()
    assert any(r["name"] == "new-room" for r in result["rooms"])


def test_post_message_to_archived_room_rejected(db):
    svc = ChatService(db)
    svc.init_room("dev")
    svc.archive_room("dev")
    with pytest.raises(ValueError, match="archived"):
        svc.post_message("dev", "alice", "should fail")


def test_read_messages(db):
    svc = ChatService(db)
    svc.post_message("dev", "alice", "msg1")
    svc.post_message("dev", "bob", "msg2")
    result = svc.read_messages("dev")
    assert len(result["messages"]) == 2
    assert result["has_more"] is False


def test_read_messages_since_id(db):
    svc = ChatService(db)
    m1 = svc.post_message("dev", "alice", "msg1")
    svc.post_message("dev", "bob", "msg2")
    result = svc.read_messages("dev", since_id=m1["id"])
    assert len(result["messages"]) == 1
    assert result["messages"][0]["content"] == "msg2"


def test_read_messages_with_limit(db):
    svc = ChatService(db)
    for i in range(5):
        svc.post_message("dev", "alice", f"msg-{i}")
    result = svc.read_messages("dev", limit=3)
    assert len(result["messages"]) == 3
    assert result["has_more"] is True


def test_read_messages_nonexistent_room(db):
    svc = ChatService(db)
    result = svc.read_messages("nope")
    assert result["messages"] == []
    assert result["has_more"] is False


def test_list_rooms(db):
    svc = ChatService(db)
    svc.init_room("dev")
    svc.init_room("staging")
    result = svc.list_rooms()
    assert len(result["rooms"]) == 2


def test_list_rooms_filter_archived(db):
    svc = ChatService(db)
    svc.init_room("dev")
    svc.init_room("staging")
    svc.archive_room("staging")
    result = svc.list_rooms(status="archived")
    assert len(result["rooms"]) == 1
    assert result["rooms"][0]["name"] == "staging"


def test_archive_room(db):
    svc = ChatService(db)
    svc.init_room("dev")
    result = svc.archive_room("dev")
    assert result["name"] == "dev"
    assert result["archived_at"] is not None


def test_archive_room_not_found(db):
    svc = ChatService(db)
    with pytest.raises(ValueError, match="not found"):
        svc.archive_room("nope")


def test_archive_room_already_archived(db):
    svc = ChatService(db)
    svc.init_room("dev")
    svc.archive_room("dev")
    with pytest.raises(ValueError, match="not found"):
        svc.archive_room("dev")


def test_list_rooms_invalid_status(db):
    svc = ChatService(db)
    with pytest.raises(ValueError, match="Invalid status"):
        svc.list_rooms(status="bogus")


def test_clear_room(db):
    svc = ChatService(db)
    svc.post_message("dev", "alice", "hello")
    svc.post_message("dev", "bob", "world")
    result = svc.clear_room("dev")
    assert result["name"] == "dev"
    assert result["deleted_count"] == 2


def test_clear_room_not_found(db):
    svc = ChatService(db)
    with pytest.raises(ValueError, match="not found"):
        svc.clear_room("nope")
