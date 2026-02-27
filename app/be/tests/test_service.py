"""Tests for ChatService business logic."""

import pytest
from team_chat_mcp.service import ChatService


def test_init_room(db):
    svc = ChatService(db)
    result = svc.init_room("proj", "dev")
    assert result["name"] == "dev"
    assert result["project"] == "proj"
    assert result["status"] == "live"
    assert "id" in result


def test_init_room_with_branch(db):
    svc = ChatService(db)
    result = svc.init_room("proj", "dev", branch="main", description="Dev room")
    assert result["branch"] == "main"
    assert result["description"] == "Dev room"


def test_init_room_idempotent(db):
    svc = ChatService(db)
    r1 = svc.init_room("proj", "dev")
    r2 = svc.init_room("proj", "dev")
    assert r1["id"] == r2["id"]


def test_init_room_same_name_different_project(db):
    svc = ChatService(db)
    r1 = svc.init_room("proj-a", "dev")
    r2 = svc.init_room("proj-b", "dev")
    assert r1["id"] != r2["id"]


def test_post_message(db):
    svc = ChatService(db)
    result = svc.post_message("proj", "dev", "alice", "hello world")
    assert result["id"] is not None
    assert result["room_id"] is not None
    assert result["sender"] == "alice"
    assert result["content"] == "hello world"
    assert result["message_type"] == "message"


def test_post_message_auto_creates_room(db):
    svc = ChatService(db)
    svc.post_message("proj", "new-room", "alice", "first message")
    result = svc.list_rooms(project="proj")
    assert any(r["name"] == "new-room" for r in result["rooms"])


def test_post_message_system_type(db):
    svc = ChatService(db)
    result = svc.post_message("proj", "dev", "system", "Room created", message_type="system")
    assert result["message_type"] == "system"


def test_post_message_to_archived_room_rejected(db):
    svc = ChatService(db)
    svc.init_room("proj", "dev")
    svc.archive_room("proj", "dev")
    with pytest.raises(ValueError, match="archived"):
        svc.post_message("proj", "dev", "alice", "should fail")


def test_read_messages(db):
    svc = ChatService(db)
    svc.post_message("proj", "dev", "alice", "msg1")
    svc.post_message("proj", "dev", "bob", "msg2")
    result = svc.read_messages("proj", "dev")
    assert len(result["messages"]) == 2
    assert result["has_more"] is False


def test_read_messages_since_id(db):
    svc = ChatService(db)
    m1 = svc.post_message("proj", "dev", "alice", "msg1")
    svc.post_message("proj", "dev", "bob", "msg2")
    result = svc.read_messages("proj", "dev", since_id=m1["id"])
    assert len(result["messages"]) == 1
    assert result["messages"][0]["content"] == "msg2"


def test_read_messages_with_limit(db):
    svc = ChatService(db)
    for i in range(5):
        svc.post_message("proj", "dev", "alice", f"msg-{i}")
    result = svc.read_messages("proj", "dev", limit=3)
    assert len(result["messages"]) == 3
    assert result["has_more"] is True


def test_read_messages_filter_by_type(db):
    svc = ChatService(db)
    svc.post_message("proj", "dev", "system", "Created", message_type="system")
    svc.post_message("proj", "dev", "alice", "hello")
    result = svc.read_messages("proj", "dev", message_type="message")
    assert len(result["messages"]) == 1


def test_read_messages_nonexistent_room(db):
    svc = ChatService(db)
    result = svc.read_messages("proj", "nope")
    assert result["messages"] == []


def test_list_rooms(db):
    svc = ChatService(db)
    svc.init_room("proj", "dev")
    svc.init_room("proj", "staging")
    result = svc.list_rooms()
    assert len(result["rooms"]) == 2


def test_list_rooms_filter_by_project(db):
    svc = ChatService(db)
    svc.init_room("proj-a", "dev")
    svc.init_room("proj-b", "dev")
    result = svc.list_rooms(project="proj-a")
    assert len(result["rooms"]) == 1


def test_list_rooms_filter_archived(db):
    svc = ChatService(db)
    svc.init_room("proj", "dev")
    svc.init_room("proj", "staging")
    svc.archive_room("proj", "staging")
    result = svc.list_rooms(status="archived")
    assert len(result["rooms"]) == 1
    assert result["rooms"][0]["name"] == "staging"


def test_list_rooms_invalid_status(db):
    svc = ChatService(db)
    with pytest.raises(ValueError, match="Invalid status"):
        svc.list_rooms(status="bogus")


def test_list_projects(db):
    svc = ChatService(db)
    svc.init_room("proj-a", "dev")
    svc.init_room("proj-b", "staging")
    result = svc.list_projects()
    assert set(result["projects"]) == {"proj-a", "proj-b"}


def test_archive_room(db):
    svc = ChatService(db)
    svc.init_room("proj", "dev")
    result = svc.archive_room("proj", "dev")
    assert result["name"] == "dev"
    assert result["archived_at"] is not None


def test_archive_room_not_found(db):
    svc = ChatService(db)
    with pytest.raises(ValueError, match="not found"):
        svc.archive_room("proj", "nope")


def test_archive_room_already_archived(db):
    svc = ChatService(db)
    svc.init_room("proj", "dev")
    svc.archive_room("proj", "dev")
    with pytest.raises(ValueError, match="not found"):
        svc.archive_room("proj", "dev")


def test_clear_room(db):
    svc = ChatService(db)
    svc.post_message("proj", "dev", "alice", "hello")
    svc.post_message("proj", "dev", "bob", "world")
    result = svc.clear_room("proj", "dev")
    assert result["name"] == "dev"
    assert result["deleted_count"] == 2


def test_clear_room_not_found(db):
    svc = ChatService(db)
    with pytest.raises(ValueError, match="not found"):
        svc.clear_room("proj", "nope")


def test_search(db):
    svc = ChatService(db)
    svc.post_message("proj", "planning", "alice", "auth feature discussion")
    result = svc.search("auth", project="proj")
    assert len(result["message_rooms"]) == 1


# --- Test 1: read_messages_by_room_id ---


def test_read_messages_by_room_id_happy_path(db):
    svc = ChatService(db)
    svc.post_message("proj", "dev", "alice", "hello")
    svc.post_message("proj", "dev", "bob", "world")
    rooms = svc.list_rooms(project="proj")
    room_id = rooms["rooms"][0]["id"]
    result = svc.read_messages_by_room_id(room_id)
    assert len(result["messages"]) == 2
    assert result["messages"][0]["sender"] == "alice"
    assert result["messages"][1]["sender"] == "bob"
    assert result["has_more"] is False


def test_read_messages_by_room_id_since_id(db):
    svc = ChatService(db)
    m1 = svc.post_message("proj", "dev", "alice", "first")
    svc.post_message("proj", "dev", "bob", "second")
    rooms = svc.list_rooms(project="proj")
    room_id = rooms["rooms"][0]["id"]
    result = svc.read_messages_by_room_id(room_id, since_id=m1["id"])
    assert len(result["messages"]) == 1
    assert result["messages"][0]["content"] == "second"


def test_read_messages_by_room_id_limit(db):
    svc = ChatService(db)
    for i in range(5):
        svc.post_message("proj", "dev", "alice", f"msg-{i}")
    rooms = svc.list_rooms(project="proj")
    room_id = rooms["rooms"][0]["id"]
    result = svc.read_messages_by_room_id(room_id, limit=3)
    assert len(result["messages"]) == 3
    assert result["has_more"] is True


def test_read_messages_by_room_id_message_type_filter(db):
    svc = ChatService(db)
    svc.post_message("proj", "dev", "system", "Room created", message_type="system")
    svc.post_message("proj", "dev", "alice", "hello")
    rooms = svc.list_rooms(project="proj")
    room_id = rooms["rooms"][0]["id"]
    result = svc.read_messages_by_room_id(room_id, message_type="message")
    assert len(result["messages"]) == 1
    assert result["messages"][0]["sender"] == "alice"


def test_read_messages_by_room_id_nonexistent(db):
    svc = ChatService(db)
    result = svc.read_messages_by_room_id("nonexistent-room-id")
    assert result["messages"] == []
    assert result["has_more"] is False


# --- Test 2: get_room_stats ---


def test_get_room_stats_with_messages(db):
    svc = ChatService(db)
    svc.post_message("proj", "dev", "alice", "hello")
    svc.post_message("proj", "dev", "bob", "world")
    svc.post_message("proj", "dev", "alice", "again")
    svc.post_message("proj", "dev", "system", "event", message_type="system")
    rooms = svc.list_rooms(project="proj")
    room_id = rooms["rooms"][0]["id"]
    stats = svc.get_room_stats(room_id)
    assert stats["message_count"] == 4
    assert stats["last_message_content"] is not None
    assert stats["last_message_ts"] is not None
    # role_counts only includes 'message' type, not 'system'
    assert stats["role_counts"]["alice"] == 2
    assert stats["role_counts"]["bob"] == 1
    assert "system" not in stats["role_counts"]


def test_get_room_stats_empty_room(db):
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    stats = svc.get_room_stats(room["id"])
    assert stats["message_count"] == 0
    assert stats["last_message_content"] is None
    assert stats["role_counts"] == {}


# --- Test 8: message_type validation ---


def test_post_message_invalid_message_type(db):
    svc = ChatService(db)
    with pytest.raises(ValueError, match="Invalid message_type"):
        svc.post_message("proj", "dev", "alice", "hello", message_type="invalid")


def test_post_message_valid_message_type(db):
    svc = ChatService(db)
    result = svc.post_message("proj", "dev", "alice", "hello", message_type="message")
    assert result["message_type"] == "message"


def test_post_message_system_message_type(db):
    svc = ChatService(db)
    result = svc.post_message("proj", "dev", "system", "event", message_type="system")
    assert result["message_type"] == "system"
