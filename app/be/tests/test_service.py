"""Tests for ChatService business logic."""

from datetime import datetime, timezone, timedelta

import pytest
from chatnut.service import ChatService


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
    svc.init_room("proj", "dev")
    result = svc.post_message("proj", "dev", "alice", "hello world")
    assert result["id"] is not None
    assert result["room_id"] is not None
    assert result["sender"] == "alice"
    assert result["content"] == "hello world"
    assert result["message_type"] == "message"


def test_post_message_requires_existing_room(db):
    svc = ChatService(db)
    with pytest.raises(ValueError, match="not found"):
        svc.post_message("proj", "new-room", "alice", "first message")


def test_post_message_system_type(db):
    svc = ChatService(db)
    svc.init_room("proj", "dev")
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
    svc.init_room("proj", "dev")
    svc.post_message("proj", "dev", "alice", "msg1")
    svc.post_message("proj", "dev", "bob", "msg2")
    result = svc.read_messages("proj", "dev")
    assert len(result["messages"]) == 2
    assert result["has_more"] is False


def test_read_messages_since_id(db):
    svc = ChatService(db)
    svc.init_room("proj", "dev")
    m1 = svc.post_message("proj", "dev", "alice", "msg1")
    svc.post_message("proj", "dev", "bob", "msg2")
    result = svc.read_messages("proj", "dev", since_id=m1["id"])
    assert len(result["messages"]) == 1
    assert result["messages"][0]["content"] == "msg2"


def test_read_messages_with_limit(db):
    svc = ChatService(db)
    svc.init_room("proj", "dev")
    for i in range(5):
        svc.post_message("proj", "dev", "alice", f"msg-{i}")
    result = svc.read_messages("proj", "dev", limit=3)
    assert len(result["messages"]) == 3
    assert result["has_more"] is True


def test_read_messages_filter_by_type(db):
    svc = ChatService(db)
    svc.init_room("proj", "dev")
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


def test_delete_room_archived(db):
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    svc.post_message("proj", "dev", "alice", "hello")
    svc.post_message("proj", "dev", "bob", "world")
    svc.archive_room("proj", "dev")
    result = svc.delete_room(room["id"])
    assert result["name"] == "dev"
    assert result["deleted_messages"] == 2
    # Room is gone
    rooms = svc.list_rooms(status="all")
    assert len(rooms["rooms"]) == 0


def test_delete_room_live_rejected(db):
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    with pytest.raises(ValueError, match="live"):
        svc.delete_room(room["id"])


def test_delete_room_not_found(db):
    svc = ChatService(db)
    with pytest.raises(ValueError, match="not found"):
        svc.delete_room("nonexistent")


def test_archive_room_already_archived(db):
    svc = ChatService(db)
    svc.init_room("proj", "dev")
    svc.archive_room("proj", "dev")
    with pytest.raises(ValueError, match="not found"):
        svc.archive_room("proj", "dev")


def test_clear_room(db):
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    svc.post_message("proj", "dev", "alice", "hello")
    svc.post_message("proj", "dev", "bob", "world")
    # Add some statuses before clearing
    svc.update_status(room["id"], "alice", "working")
    svc.update_status(room["id"], "bob", "idle")
    result = svc.clear_room("proj", "dev")
    assert result["name"] == "dev"
    assert result["deleted_count"] == 2
    # Verify room_status records are also deleted after clear_room
    status_result = svc.get_team_status(room["id"])
    assert status_result["statuses"] == []


def test_clear_room_not_found(db):
    svc = ChatService(db)
    with pytest.raises(ValueError, match="not found"):
        svc.clear_room("proj", "nope")


def test_search(db):
    svc = ChatService(db)
    svc.init_room("proj", "planning")
    svc.post_message("proj", "planning", "alice", "auth feature discussion")
    result = svc.search("auth", project="proj")
    assert len(result["message_rooms"]) == 1


# --- Test 1: read_messages_by_room_id ---


def test_read_messages_by_room_id_happy_path(db):
    svc = ChatService(db)
    svc.init_room("proj", "dev")
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
    svc.init_room("proj", "dev")
    m1 = svc.post_message("proj", "dev", "alice", "first")
    svc.post_message("proj", "dev", "bob", "second")
    rooms = svc.list_rooms(project="proj")
    room_id = rooms["rooms"][0]["id"]
    result = svc.read_messages_by_room_id(room_id, since_id=m1["id"])
    assert len(result["messages"]) == 1
    assert result["messages"][0]["content"] == "second"


def test_read_messages_by_room_id_limit(db):
    svc = ChatService(db)
    svc.init_room("proj", "dev")
    for i in range(5):
        svc.post_message("proj", "dev", "alice", f"msg-{i}")
    rooms = svc.list_rooms(project="proj")
    room_id = rooms["rooms"][0]["id"]
    result = svc.read_messages_by_room_id(room_id, limit=3)
    assert len(result["messages"]) == 3
    assert result["has_more"] is True


def test_read_messages_by_room_id_message_type_filter(db):
    svc = ChatService(db)
    svc.init_room("proj", "dev")
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


# --- Test 2: get_all_room_stats ---


def test_get_all_room_stats(db):
    svc = ChatService(db)
    svc.init_room("proj", "room1")
    svc.init_room("proj", "room2")
    svc.post_message("proj", "room1", "alice", "hello")
    svc.post_message("proj", "room1", "bob", "world")
    svc.post_message("proj", "room2", "carol", "hi there")
    svc.post_message("proj", "room2", "system", "joined", message_type="system")
    rooms = svc.list_rooms(project="proj")
    room_ids = [r["id"] for r in rooms["rooms"]]
    stats = svc.get_all_room_stats(room_ids)
    assert len(stats) == 2
    r1_id = next(r["id"] for r in rooms["rooms"] if r["name"] == "room1")
    r2_id = next(r["id"] for r in rooms["rooms"] if r["name"] == "room2")
    assert stats[r1_id]["message_count"] == 2
    assert stats[r1_id]["last_message_id"] is not None
    assert stats[r1_id]["last_message_ts"] is not None
    assert stats[r1_id]["role_counts"] == {"alice": 1, "bob": 1}
    assert stats[r2_id]["message_count"] == 2
    assert stats[r2_id]["last_message_id"] is not None
    assert stats[r2_id]["last_message_ts"] is not None
    # last_message_content is by MAX(id) — the system "joined" message has highest id
    assert stats[r2_id]["last_message_content"] == "joined"
    assert stats[r2_id]["role_counts"] == {"carol": 1}


# --- Test 8: message_type validation ---


def test_post_message_invalid_message_type(db):
    svc = ChatService(db)
    with pytest.raises(ValueError, match="Invalid message_type"):
        svc.post_message("proj", "dev", "alice", "hello", message_type="invalid")


def test_post_message_valid_message_type(db):
    svc = ChatService(db)
    svc.init_room("proj", "dev")
    result = svc.post_message("proj", "dev", "alice", "hello", message_type="message")
    assert result["message_type"] == "message"


def test_post_message_system_message_type(db):
    svc = ChatService(db)
    svc.init_room("proj", "dev")
    result = svc.post_message("proj", "dev", "system", "event", message_type="system")
    assert result["message_type"] == "system"


# --- Auto-archive stale rooms ---


def _set_room_created_at(db, room_id: str, ts: str):
    """Backdate a room's created_at for testing."""
    db.execute("UPDATE rooms SET created_at=? WHERE id=?", (ts, room_id))
    db.commit()


def _set_last_message_ts(db, room_id: str, ts: str):
    """Backdate all messages in a room for testing."""
    db.execute("UPDATE messages SET created_at=? WHERE room_id=?", (ts, room_id))
    db.commit()


def test_auto_archive_stale_room_with_old_messages(db):
    """Room with messages older than threshold gets archived."""
    svc = ChatService(db)
    room = svc.init_room("proj", "stale-room")
    svc.post_message("proj", "stale-room", "alice", "hello")
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    _set_last_message_ts(db, room["id"], old_ts)

    archived = svc.auto_archive_stale_rooms(max_inactive_seconds=7200)
    assert len(archived) == 1
    assert archived[0]["name"] == "stale-room"
    assert archived[0]["status"] == "archived"


def test_auto_archive_empty_room_created_long_ago(db):
    """Empty room created before threshold gets archived."""
    svc = ChatService(db)
    room = svc.init_room("proj", "empty-old")
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    _set_room_created_at(db, room["id"], old_ts)

    archived = svc.auto_archive_stale_rooms(max_inactive_seconds=7200)
    assert len(archived) == 1
    assert archived[0]["name"] == "empty-old"


def test_auto_archive_skips_active_room(db):
    """Room with recent messages is not archived."""
    svc = ChatService(db)
    svc.init_room("proj", "active-room")
    svc.post_message("proj", "active-room", "alice", "just now")

    archived = svc.auto_archive_stale_rooms(max_inactive_seconds=7200)
    assert len(archived) == 0
    rooms = svc.list_rooms(status="live", project="proj")
    assert len(rooms["rooms"]) == 1


def test_auto_archive_skips_already_archived(db):
    """Already-archived rooms are not touched."""
    svc = ChatService(db)
    svc.init_room("proj", "old-archived")
    svc.archive_room("proj", "old-archived")

    archived = svc.auto_archive_stale_rooms(max_inactive_seconds=7200)
    assert len(archived) == 0


def test_auto_archive_mixed_rooms(db):
    """Only stale live rooms are archived; active and already-archived are skipped."""
    svc = ChatService(db)
    # Stale room (old messages)
    stale = svc.init_room("proj", "stale")
    svc.post_message("proj", "stale", "alice", "old msg")
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    _set_last_message_ts(db, stale["id"], old_ts)

    # Active room (recent messages)
    svc.init_room("proj", "active")
    svc.post_message("proj", "active", "bob", "recent")

    # Already archived
    svc.init_room("proj", "done")
    svc.archive_room("proj", "done")

    archived = svc.auto_archive_stale_rooms(max_inactive_seconds=7200)
    assert len(archived) == 1
    assert archived[0]["name"] == "stale"

    # Verify final state
    live = svc.list_rooms(status="live", project="proj")
    assert len(live["rooms"]) == 1
    assert live["rooms"][0]["name"] == "active"


# --- mark_read and get_unread_counts ---


def test_mark_read(db):
    """mark_read advances cursor and returns updated position."""
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    svc.post_message("proj", "dev", "alice", "hello")
    m2 = svc.post_message("proj", "dev", "alice", "world")
    result = svc.mark_read(room["id"], "bob", m2["id"])
    assert result["room_id"] == room["id"]
    assert result["reader"] == "bob"
    assert result["last_read_message_id"] == m2["id"]


def test_mark_read_nonexistent_room(db):
    svc = ChatService(db)
    with pytest.raises(ValueError, match="not found"):
        svc.mark_read("nonexistent", "bob", 1)


def test_mark_read_empty_reader(db):
    """mark_read rejects empty reader string."""
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    with pytest.raises(ValueError, match="non-empty"):
        svc.mark_read(room["id"], "", 1)
    with pytest.raises(ValueError, match="non-empty"):
        svc.mark_read(room["id"], "   ", 1)


def test_mark_read_negative_cursor(db):
    """mark_read rejects negative last_read_message_id."""
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    with pytest.raises(ValueError, match=">= 0"):
        svc.mark_read(room["id"], "bob", -1)


def test_mark_read_beyond_max_message_id(db):
    """mark_read with cursor beyond max message ID is accepted (forward-only design)."""
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    svc.post_message("proj", "dev", "alice", "hello")
    # Set cursor far beyond actual max — this is valid by design
    result = svc.mark_read(room["id"], "bob", 99999)
    assert result["last_read_message_id"] == 99999
    # Unread count should be 0 (cursor is past all messages)
    counts = svc.get_unread_counts([room["id"]], "bob")
    assert counts[room["id"]] == 0


def test_mark_read_cursor_does_not_regress(db):
    """Forward-only: marking read at lower ID does not move cursor backward."""
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    m1 = svc.post_message("proj", "dev", "alice", "first")
    m2 = svc.post_message("proj", "dev", "alice", "second")

    svc.mark_read(room["id"], "bob", m2["id"])
    result = svc.mark_read(room["id"], "bob", m1["id"])

    assert result["last_read_message_id"] == m2["id"]


def test_get_unread_counts_service(db):
    svc = ChatService(db)
    r1 = svc.init_room("proj", "room1")
    r2 = svc.init_room("proj", "room2")
    svc.post_message("proj", "room1", "alice", "msg1")
    m1_2 = svc.post_message("proj", "room1", "alice", "msg2")
    svc.post_message("proj", "room2", "bob", "msg1")
    svc.mark_read(r1["id"], "viewer", m1_2["id"])
    result = svc.get_unread_counts([r1["id"], r2["id"]], "viewer")
    assert result[r1["id"]] == 0
    assert result[r2["id"]] == 1


def test_get_unread_counts_no_reader(db):
    """All messages unread when reader has no cursors."""
    svc = ChatService(db)
    r = svc.init_room("proj", "dev")
    svc.post_message("proj", "dev", "alice", "hello")
    svc.post_message("proj", "dev", "alice", "world")
    result = svc.get_unread_counts([r["id"]], "new-reader")
    assert result[r["id"]] == 2


def test_db_delete_room_transactional(db):
    """L1: db.delete_room deletes messages and room in one transaction."""
    from chatnut.db import create_room, insert_message, delete_room, get_room_by_id, get_messages
    room = create_room(db, project="proj", name="to-delete")
    insert_message(db, room.id, "alice", "msg1")
    insert_message(db, room.id, "bob", "msg2")
    # Archive first (delete_room doesn't check status — that's service layer)
    db.execute("UPDATE rooms SET status='archived' WHERE id=?", (room.id,))
    db.commit()
    msg_count = delete_room(db, room.id)
    assert msg_count == 2
    # Room should be gone
    assert get_room_by_id(db, room.id) is None
    # Messages should be gone
    msgs, _ = get_messages(db, room.id)
    assert len(msgs) == 0


def test_db_path_returns_string(db):
    """ChatService.db_path() returns a string (empty for :memory:, path for file DBs)."""
    from chatnut.service import ChatService
    svc = ChatService(db)
    path = svc.db_path()
    assert path == ""


def test_search_rejects_empty_query(db):
    """ChatService.search() raises ValueError for empty or whitespace-only queries."""
    from chatnut.service import ChatService
    svc = ChatService(db)
    with pytest.raises(ValueError, match="query"):
        svc.search("")
    with pytest.raises(ValueError, match="query"):
        svc.search("   ")


# --- update_status and get_team_status ---


def test_update_status(db):
    """update_status stores a sender's status in the room."""
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    result = svc.update_status(room["id"], "alice", "working on auth")
    assert result["room_id"] == room["id"]
    assert result["sender"] == "alice"
    assert result["status"] == "working on auth"
    assert "updated_at" in result


def test_update_status_upsert(db):
    """update_status overwrites a sender's previous status (upsert semantics)."""
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    svc.update_status(room["id"], "alice", "idle")
    result = svc.update_status(room["id"], "alice", "reviewing PR")
    assert result["status"] == "reviewing PR"


def test_update_status_nonexistent_room(db):
    """update_status raises ValueError for a nonexistent room."""
    svc = ChatService(db)
    with pytest.raises(ValueError, match="not found"):
        svc.update_status("nonexistent-room-id", "alice", "working")


def test_update_status_archived_room(db):
    """update_status raises ValueError for an archived room."""
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    svc.archive_room("proj", "dev")
    with pytest.raises(ValueError, match="archived"):
        svc.update_status(room["id"], "alice", "working")


def test_get_team_status(db):
    """get_team_status returns all sender statuses for a room, ordered by updated_at DESC then sender ASC."""
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    svc.update_status(room["id"], "alice", "coding")
    svc.update_status(room["id"], "bob", "reviewing")
    result = svc.get_team_status(room["id"])
    assert "statuses" in result
    statuses = result["statuses"]
    assert len(statuses) == 2
    senders = {s["sender"] for s in statuses}
    assert senders == {"alice", "bob"}
    for entry in statuses:
        assert "room_id" in entry
        assert "status" in entry
        assert "updated_at" in entry
    # Verify deterministic ordering: updated_at DESC, then sender ASC
    # bob was updated last, so bob should come first
    assert statuses[0]["sender"] == "bob"
    assert statuses[1]["sender"] == "alice"


def test_get_team_status_empty(db):
    """get_team_status returns an empty statuses list when no statuses have been set."""
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    result = svc.get_team_status(room["id"])
    assert result == {"statuses": []}


def test_get_team_status_nonexistent_room(db):
    """get_team_status raises ValueError for a nonexistent room."""
    svc = ChatService(db)
    with pytest.raises(ValueError, match="not found"):
        svc.get_team_status("nonexistent-room-id")


def test_update_status_empty_sender(db):
    """update_status rejects empty sender string."""
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    with pytest.raises(ValueError, match="sender must be a non-empty"):
        svc.update_status(room["id"], "", "working")
    with pytest.raises(ValueError, match="sender must be a non-empty"):
        svc.update_status(room["id"], "   ", "working")


def test_update_status_empty_status(db):
    """update_status rejects empty status string."""
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    with pytest.raises(ValueError, match="status must be a non-empty"):
        svc.update_status(room["id"], "alice", "")
    with pytest.raises(ValueError, match="status must be a non-empty"):
        svc.update_status(room["id"], "alice", "   ")


def test_update_status_max_length_accepted(db):
    """update_status accepts status of exactly 500 characters."""
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    result = svc.update_status(room["id"], "alice", "x" * 500)
    assert result["status"] == "x" * 500


def test_update_status_too_long(db):
    """update_status rejects status longer than 500 characters."""
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    with pytest.raises(ValueError, match="500 characters"):
        svc.update_status(room["id"], "alice", "x" * 501)


# --- Agent Registration & Mention Detection ---


def test_register_agent(db):
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    result = svc.register_agent(room["id"], "security", "task-abc")
    assert result["agent_name"] == "security"
    assert result["task_id"] == "task-abc"


def test_register_agent_normalizes_name(db):
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    svc.register_agent(room["id"], "  Security  ", "task-abc")
    result = svc.list_agents(room["id"])
    assert result["agents"][0]["agent_name"] == "security"


def test_register_agent_nonexistent_room(db):
    svc = ChatService(db)
    with pytest.raises(ValueError, match="not found"):
        svc.register_agent("nonexistent-id", "security", "task-abc")


def test_register_agent_archived_room(db):
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    svc.archive_room("proj", "dev")
    with pytest.raises(ValueError, match="archived"):
        svc.register_agent(room["id"], "security", "task-abc")


def test_register_agent_empty_name(db):
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    with pytest.raises(ValueError, match="agent_name"):
        svc.register_agent(room["id"], "", "task-abc")


def test_register_agent_empty_task_id(db):
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    with pytest.raises(ValueError, match="task_id"):
        svc.register_agent(room["id"], "security", "")


def test_post_message_detects_single_mention(db):
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    svc.register_agent(room["id"], "security", "task-abc")
    result = svc.post_message_by_room_id(room["id"], "pm", "@security please review")
    assert result["mentions"] == [{"name": "security", "task_id": "task-abc"}]


def test_post_message_detects_multiple_mentions(db):
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    svc.register_agent(room["id"], "security", "task-abc")
    svc.register_agent(room["id"], "architect", "task-def")
    result = svc.post_message_by_room_id(room["id"], "pm", "@security @architect check this")
    names = {m["name"] for m in result["mentions"]}
    assert names == {"security", "architect"}


def test_post_message_skips_unregistered_mentions(db):
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    svc.register_agent(room["id"], "security", "task-abc")
    result = svc.post_message_by_room_id(room["id"], "pm", "@security @unknown check this")
    assert len(result["mentions"]) == 1
    assert result["mentions"][0]["name"] == "security"


def test_post_message_no_mentions_returns_empty(db):
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    result = svc.post_message_by_room_id(room["id"], "pm", "no mentions here")
    assert result["mentions"] == []


def test_post_message_mention_in_middle(db):
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    svc.register_agent(room["id"], "backend-dev", "task-xyz")
    result = svc.post_message_by_room_id(room["id"], "pm", "hey @backend-dev can you check?")
    assert result["mentions"] == [{"name": "backend-dev", "task_id": "task-xyz"}]


def test_post_message_deduplicates_mentions(db):
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    svc.register_agent(room["id"], "security", "task-abc")
    result = svc.post_message_by_room_id(room["id"], "pm", "@security @security please review")
    assert len(result["mentions"]) == 1


def test_post_message_mention_case_insensitive(db):
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    svc.register_agent(room["id"], "security", "task-abc")
    result = svc.post_message_by_room_id(room["id"], "pm", "@Security please review")
    assert result["mentions"] == [{"name": "security", "task_id": "task-abc"}]


def test_post_message_no_false_mention_in_email(db):
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    svc.register_agent(room["id"], "example", "task-abc")
    result = svc.post_message_by_room_id(room["id"], "pm", "contact user@example.com for details")
    assert result["mentions"] == []


def test_post_message_no_false_mention_hello_at_name(db):
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    svc.register_agent(room["id"], "name", "task-abc")
    result = svc.post_message_by_room_id(room["id"], "pm", "Hello@name how are you")
    assert result["mentions"] == []


def test_post_message_mention_after_newline(db):
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    svc.register_agent(room["id"], "security", "task-abc")
    result = svc.post_message_by_room_id(room["id"], "pm", "first line\n@security check this")
    assert result["mentions"] == [{"name": "security", "task_id": "task-abc"}]


def test_post_message_mention_after_punctuation(db):
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    svc.register_agent(room["id"], "security", "task-abc")
    result = svc.post_message_by_room_id(room["id"], "pm", "(@security) check this")
    assert result["mentions"] == [{"name": "security", "task_id": "task-abc"}]


def test_post_message_by_name_also_detects_mentions(db):
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    svc.register_agent(room["id"], "security", "task-abc")
    result = svc.post_message("proj", "dev", "pm", "@security check this")
    assert result["mentions"] == [{"name": "security", "task_id": "task-abc"}]


def test_list_agents(db):
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    svc.register_agent(room["id"], "security", "task-abc")
    svc.register_agent(room["id"], "architect", "task-def")
    result = svc.list_agents(room["id"])
    assert len(result["agents"]) == 2
    names = {a["agent_name"] for a in result["agents"]}
    assert names == {"security", "architect"}


def test_list_agents_nonexistent_room(db):
    svc = ChatService(db)
    with pytest.raises(ValueError, match="not found"):
        svc.list_agents("nonexistent-id")


def test_list_agents_archived_room_allowed(db):
    """list_agents is a read-only operation — archived rooms are allowed."""
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    svc.register_agent(room["id"], "security", "task-abc")
    svc.archive_room("proj", "dev")
    result = svc.list_agents(room["id"])
    assert len(result["agents"]) == 1
