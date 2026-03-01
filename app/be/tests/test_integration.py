"""Integration tests — verify full tool flows end-to-end via ChatService."""

import pytest
from agent_chat_mcp.service import ChatService


def test_full_lifecycle(db):
    """Room creation -> post messages -> read -> archive -> reject post."""
    svc = ChatService(db)

    # Create room
    room = svc.init_room("proj", "integration-test")
    assert room["status"] == "live"
    assert room["project"] == "proj"

    # Post messages
    m1 = svc.post_message("proj", "integration-test", "alice", "hello")
    m2 = svc.post_message("proj", "integration-test", "bob", "world")

    # Read all
    result = svc.read_messages("proj", "integration-test")
    assert len(result["messages"]) == 2

    # Read incremental
    result = svc.read_messages("proj", "integration-test", since_id=m1["id"])
    assert len(result["messages"]) == 1
    assert result["messages"][0]["sender"] == "bob"

    # Archive
    archived = svc.archive_room("proj", "integration-test")
    assert archived["archived_at"] is not None

    # Verify post to archived room fails
    with pytest.raises(ValueError, match="archived"):
        svc.post_message("proj", "integration-test", "alice", "should fail")

    # Messages still readable after archive
    result = svc.read_messages("proj", "integration-test")
    assert len(result["messages"]) == 2


def test_post_message_requires_existing_room(db):
    """post_message should raise ValueError if room doesn't exist."""
    svc = ChatService(db)
    with pytest.raises(ValueError, match="not found"):
        svc.post_message("proj", "no-such-room", "alice", "first message")


def test_clear_room_preserves_room(db):
    """clear_room deletes messages but keeps the room record."""
    svc = ChatService(db)
    svc.init_room("proj", "clear-test")
    svc.post_message("proj", "clear-test", "alice", "hello")
    svc.post_message("proj", "clear-test", "bob", "world")

    result = svc.clear_room("proj", "clear-test")
    assert result["deleted_count"] == 2

    # Room still exists
    rooms = svc.list_rooms(project="proj")
    names = [r["name"] for r in rooms["rooms"]]
    assert "clear-test" in names

    # No messages remain
    msgs = svc.read_messages("proj", "clear-test")
    assert len(msgs["messages"]) == 0


def test_cross_project_isolation(db):
    """Rooms with same name in different projects are independent."""
    svc = ChatService(db)
    svc.init_room("proj-a", "dev")
    svc.init_room("proj-b", "dev")
    svc.post_message("proj-a", "dev", "alice", "message in proj-a")
    svc.post_message("proj-b", "dev", "bob", "message in proj-b")

    result_a = svc.read_messages("proj-a", "dev")
    result_b = svc.read_messages("proj-b", "dev")
    assert len(result_a["messages"]) == 1
    assert result_a["messages"][0]["sender"] == "alice"
    assert len(result_b["messages"]) == 1
    assert result_b["messages"][0]["sender"] == "bob"


def test_message_types(db):
    """System and regular messages coexist, can be filtered."""
    svc = ChatService(db)
    svc.init_room("proj", "dev")
    svc.post_message("proj", "dev", "system", "Room created", message_type="system")
    svc.post_message("proj", "dev", "alice", "hello")
    svc.post_message("proj", "dev", "bob", "world")

    all_msgs = svc.read_messages("proj", "dev")
    assert len(all_msgs["messages"]) == 3

    regular_only = svc.read_messages("proj", "dev", message_type="message")
    assert len(regular_only["messages"]) == 2

    system_only = svc.read_messages("proj", "dev", message_type="system")
    assert len(system_only["messages"]) == 1


def test_search_across_rooms(db):
    """Search finds matches in room names and message content."""
    svc = ChatService(db)
    svc.init_room("proj", "planning")
    svc.init_room("proj", "dev")
    svc.init_room("proj", "ops")
    svc.post_message("proj", "planning", "alice", "discuss auth feature")
    svc.post_message("proj", "dev", "bob", "implement auth handler")
    svc.post_message("proj", "ops", "charlie", "deploy staging")

    result = svc.search("auth", project="proj")
    assert len(result["message_rooms"]) == 2  # planning + dev have "auth"


def test_list_projects(db):
    """list_projects returns distinct project names."""
    svc = ChatService(db)
    svc.init_room("proj-a", "dev")
    svc.init_room("proj-b", "staging")
    svc.init_room("proj-a", "ops")

    result = svc.list_projects()
    assert set(result["projects"]) == {"proj-a", "proj-b"}


def test_unread_read_round_trip(db):
    """Full round-trip: post messages -> check unread -> mark read -> check unread again."""
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    svc.post_message("proj", "dev", "alice", "msg1")
    svc.post_message("proj", "dev", "alice", "msg2")
    m3 = svc.post_message("proj", "dev", "alice", "msg3")

    # Before reading: all 3 unread
    counts = svc.get_unread_counts([room["id"]], "bob")
    assert counts[room["id"]] == 3

    # Mark read up to msg3
    svc.mark_read(room["id"], "bob", m3["id"])

    # After reading: 0 unread
    counts = svc.get_unread_counts([room["id"]], "bob")
    assert counts[room["id"]] == 0

    # New message arrives
    svc.post_message("proj", "dev", "alice", "msg4")

    # 1 unread
    counts = svc.get_unread_counts([room["id"]], "bob")
    assert counts[room["id"]] == 1


def test_unread_counts_multi_reader(db):
    """Different readers have independent cursors."""
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    m1 = svc.post_message("proj", "dev", "alice", "msg1")
    svc.post_message("proj", "dev", "alice", "msg2")

    svc.mark_read(room["id"], "bob", m1["id"])

    bob_counts = svc.get_unread_counts([room["id"]], "bob")
    carol_counts = svc.get_unread_counts([room["id"]], "carol")
    assert bob_counts[room["id"]] == 1    # read msg1, msg2 unread
    assert carol_counts[room["id"]] == 2  # never read


def test_delete_room_cascades_read_cursors(db):
    """Deleting a room also deletes its read cursors (ON DELETE CASCADE)."""
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    msg = svc.post_message("proj", "dev", "alice", "hello")
    svc.mark_read(room["id"], "bob", msg["id"])
    svc.archive_room("proj", "dev")
    svc.delete_room(room["id"])
    # Cursor should be gone (no orphaned data)
    from agent_chat_mcp.db import get_read_cursor
    assert get_read_cursor(db, room["id"], "bob") is None
