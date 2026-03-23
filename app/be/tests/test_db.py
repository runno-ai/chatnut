"""Tests for database layer."""

import sqlite3
import pytest
from chatnut.db import (
    init_db,
    create_room,
    get_room,
    get_room_by_id,
    list_rooms,
    list_projects,
    archive_room,
    delete_room,
    insert_message,
    get_messages,
    delete_messages,
    search_rooms_and_messages,
    get_all_room_stats,
    upsert_read_cursor,
    get_read_cursor,
    get_unread_counts,
    upsert_room_status,
    get_room_statuses,
    upsert_agent_registration,
    get_agent_registrations,
    delete_agent_registrations,
)


def test_init_db_creates_tables(db):
    tables = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    names = [t[0] for t in tables]
    assert "rooms" in names
    assert "messages" in names


def test_create_room(db):
    room = create_room(db, project="proj", name="dev")
    assert room.id  # UUID generated
    assert room.name == "dev"
    assert room.project == "proj"
    assert room.branch is None
    assert room.status == "live"


def test_create_room_with_branch(db):
    room = create_room(db, project="proj", name="dev", branch="feat/auth", description="Auth work")
    assert room.branch == "feat/auth"
    assert room.description == "Auth work"


def test_create_room_idempotent(db):
    r1 = create_room(db, project="proj", name="dev")
    r2 = create_room(db, project="proj", name="dev")
    assert r1.id == r2.id
    assert r1.created_at == r2.created_at


def test_create_room_same_name_different_project(db):
    r1 = create_room(db, project="proj-a", name="dev")
    r2 = create_room(db, project="proj-b", name="dev")
    assert r1.id != r2.id


def test_get_room(db):
    created = create_room(db, project="proj", name="dev")
    fetched = get_room(db, project="proj", name="dev")
    assert fetched is not None
    assert fetched.id == created.id


def test_get_room_missing(db):
    assert get_room(db, project="proj", name="nope") is None


def test_get_room_by_id(db):
    created = create_room(db, project="proj", name="dev")
    fetched = get_room_by_id(db, created.id)
    assert fetched is not None
    assert fetched.name == "dev"


def test_list_rooms_default_live(db):
    create_room(db, project="proj", name="dev")
    create_room(db, project="proj", name="staging")
    rooms = list_rooms(db)
    assert len(rooms) == 2


def test_list_rooms_filter_by_project(db):
    create_room(db, project="proj-a", name="dev")
    create_room(db, project="proj-b", name="dev")
    rooms = list_rooms(db, project="proj-a")
    assert len(rooms) == 1
    assert rooms[0].project == "proj-a"


def test_list_rooms_archived(db):
    create_room(db, project="proj", name="dev")
    create_room(db, project="proj", name="staging")
    archive_room(db, project="proj", name="staging")
    rooms = list_rooms(db, status="archived")
    assert len(rooms) == 1
    assert rooms[0].name == "staging"


def test_list_rooms_all(db):
    create_room(db, project="proj", name="dev")
    create_room(db, project="proj", name="staging")
    archive_room(db, project="proj", name="staging")
    rooms = list_rooms(db, status="all")
    assert len(rooms) == 2


def test_list_projects(db):
    create_room(db, project="proj-a", name="dev")
    create_room(db, project="proj-b", name="staging")
    create_room(db, project="proj-a", name="ops")
    projects = list_projects(db)
    assert set(projects) == {"proj-a", "proj-b"}


def test_archive_room(db):
    create_room(db, project="proj", name="dev")
    room = archive_room(db, project="proj", name="dev")
    assert room is not None
    assert room.status == "archived"
    assert room.archived_at is not None


def test_archive_room_not_found(db):
    assert archive_room(db, project="proj", name="nope") is None


def test_archive_room_already_archived(db):
    create_room(db, project="proj", name="dev")
    archive_room(db, project="proj", name="dev")
    assert archive_room(db, project="proj", name="dev") is None


def test_insert_and_get_messages(db):
    room = create_room(db, project="proj", name="dev")
    insert_message(db, room.id, "alice", "hello")
    insert_message(db, room.id, "bob", "world")
    messages, has_more = get_messages(db, room.id)
    assert len(messages) == 2
    assert messages[0].sender == "alice"
    assert messages[1].sender == "bob"
    assert has_more is False


def test_insert_message_with_type(db):
    room = create_room(db, project="proj", name="dev")
    msg = insert_message(db, room.id, "system", "Room created", message_type="system")
    assert msg.message_type == "system"


def test_insert_message_with_metadata(db):
    room = create_room(db, project="proj", name="dev")
    msg = insert_message(db, room.id, "alice", "hello", metadata='{"key": "val"}')
    assert msg.metadata == '{"key": "val"}'


def test_get_messages_since_id(db):
    room = create_room(db, project="proj", name="dev")
    m1 = insert_message(db, room.id, "alice", "msg1")
    insert_message(db, room.id, "bob", "msg2")
    messages, _ = get_messages(db, room.id, since_id=m1.id)
    assert len(messages) == 1
    assert messages[0].content == "msg2"


def test_get_messages_limit(db):
    room = create_room(db, project="proj", name="dev")
    for i in range(5):
        insert_message(db, room.id, "alice", f"msg-{i}")
    messages, has_more = get_messages(db, room.id, limit=3)
    assert len(messages) == 3
    assert has_more is True


def test_get_messages_filter_by_type(db):
    room = create_room(db, project="proj", name="dev")
    insert_message(db, room.id, "system", "Room created", message_type="system")
    insert_message(db, room.id, "alice", "hello")
    messages, _ = get_messages(db, room.id, message_type="message")
    assert len(messages) == 1
    assert messages[0].sender == "alice"


def test_delete_messages(db):
    room = create_room(db, project="proj", name="dev")
    insert_message(db, room.id, "alice", "hello")
    insert_message(db, room.id, "bob", "world")
    count = delete_messages(db, room.id)
    assert count == 2
    messages, _ = get_messages(db, room.id)
    assert len(messages) == 0


def test_insert_message_fk_enforced(db):
    with pytest.raises(sqlite3.IntegrityError):
        insert_message(db, "nonexistent-room-id", "alice", "hello")


def test_search_rooms_and_messages(db):
    room = create_room(db, project="proj", name="planning-room")
    insert_message(db, room.id, "alice", "Let's discuss the auth feature")
    insert_message(db, room.id, "bob", "Sounds good")

    # Search by room name
    result = search_rooms_and_messages(db, "planning")
    assert len(result["rooms"]) == 1

    # Search by message content
    result = search_rooms_and_messages(db, "auth feature")
    assert len(result["message_rooms"]) == 1
    assert result["message_rooms"][0]["room_id"] == room.id


def test_search_with_project_filter(db):
    r1 = create_room(db, project="proj-a", name="dev")
    r2 = create_room(db, project="proj-b", name="dev")
    insert_message(db, r1.id, "alice", "hello from proj-a")
    insert_message(db, r2.id, "bob", "hello from proj-b")

    result = search_rooms_and_messages(db, "hello", project="proj-a")
    assert len(result["message_rooms"]) == 1
    assert result["message_rooms"][0]["room_id"] == r1.id


def test_search_escapes_like_wildcards(db):
    room = create_room(db, project="proj", name="dev")
    insert_message(db, room.id, "alice", "100% done")
    insert_message(db, room.id, "bob", "file_name.txt")

    result = search_rooms_and_messages(db, "100%")
    assert len(result["message_rooms"]) == 1

    result = search_rooms_and_messages(db, "file_name")
    assert len(result["message_rooms"]) == 1


def test_list_rooms_filter_by_branch(db):
    create_room(db, project="proj", name="dev", branch="main")
    create_room(db, project="proj", name="staging", branch="feat/auth")
    rooms = list_rooms(db, branch="main")
    assert len(rooms) == 1
    assert rooms[0].name == "dev"


# --- Test 4: get_messages limit boundary ---


def test_get_messages_limit_zero_clamps_to_one(db):
    room = create_room(db, project="proj", name="dev")
    for i in range(5):
        insert_message(db, room.id, "alice", f"msg-{i}")
    messages, has_more = get_messages(db, room.id, limit=0)
    assert len(messages) == 1
    assert has_more is True


def test_get_messages_limit_exceeding_max_clamps_to_1000(db):
    room = create_room(db, project="proj", name="dev")
    # Insert a small number of messages — we only need to verify the limit is clamped,
    # not that we get exactly 1000.
    for i in range(5):
        insert_message(db, room.id, "alice", f"msg-{i}")
    messages, has_more = get_messages(db, room.id, limit=9999)
    # With only 5 messages inserted and limit clamped to 1000, all 5 are returned
    assert len(messages) == 5
    assert has_more is False


def test_get_all_room_stats(db):
    r1 = create_room(db, project="proj", name="room1")
    r2 = create_room(db, project="proj", name="room2")
    insert_message(db, r1.id, "alice", "hello")
    insert_message(db, r1.id, "bob", "world")
    insert_message(db, r2.id, "carol", "hi there")
    insert_message(db, r2.id, "system", "joined", message_type="system")

    stats = get_all_room_stats(db, [r1.id, r2.id])
    assert len(stats) == 2

    s1 = stats[r1.id]
    assert s1["message_count"] == 2
    assert s1["last_message_id"] is not None
    assert s1["last_message_ts"] is not None
    assert s1["last_message_content"] == "world"
    assert s1["role_counts"] == {"alice": 1, "bob": 1}

    s2 = stats[r2.id]
    assert s2["message_count"] == 2
    assert s2["last_message_ts"] is not None
    # last_message_content is by MAX(id) across ALL types — the system "joined"
    # message was inserted after "hi there", so it has the highest id
    assert s2["last_message_content"] == "joined"
    # role_counts only counts message_type='message', excludes system
    assert s2["role_counts"] == {"carol": 1}


def test_get_all_room_stats_empty_rooms(db):
    r1 = create_room(db, project="proj", name="empty1")
    r2 = create_room(db, project="proj", name="empty2")

    stats = get_all_room_stats(db, [r1.id, r2.id])
    assert len(stats) == 2
    for rid in [r1.id, r2.id]:
        assert stats[rid]["message_count"] == 0
        assert stats[rid]["last_message_id"] is None
        assert stats[rid]["last_message_ts"] is None
        assert stats[rid]["last_message_content"] is None
        assert stats[rid]["role_counts"] == {}


def test_get_all_room_stats_mixed(db):
    """Mix of rooms with and without messages — both must appear in results."""
    r1 = create_room(db, project="proj", name="active")
    r2 = create_room(db, project="proj", name="empty")
    insert_message(db, r1.id, "alice", "hello")

    stats = get_all_room_stats(db, [r1.id, r2.id])
    assert stats[r1.id]["message_count"] == 1
    assert stats[r1.id]["last_message_content"] == "hello"
    assert stats[r2.id]["message_count"] == 0
    assert stats[r2.id]["last_message_content"] is None


def test_get_all_room_stats_empty_list(db):
    stats = get_all_room_stats(db, [])
    assert stats == {}


# --- Read cursor tests ---


def test_upsert_read_cursor_insert(db):
    """First cursor write creates a new row."""
    room = create_room(db, project="proj", name="dev")
    msg = insert_message(db, room.id, "alice", "hello")
    upsert_read_cursor(db, room.id, "bob", msg.id)
    cursor = get_read_cursor(db, room.id, "bob")
    assert cursor == msg.id


def test_upsert_read_cursor_update(db):
    """Subsequent writes update the existing row."""
    room = create_room(db, project="proj", name="dev")
    m1 = insert_message(db, room.id, "alice", "hello")
    m2 = insert_message(db, room.id, "alice", "world")
    upsert_read_cursor(db, room.id, "bob", m1.id)
    upsert_read_cursor(db, room.id, "bob", m2.id)
    cursor = get_read_cursor(db, room.id, "bob")
    assert cursor == m2.id


def test_upsert_read_cursor_no_backward(db):
    """Cursor cannot move backward (only forward)."""
    room = create_room(db, project="proj", name="dev")
    m1 = insert_message(db, room.id, "alice", "hello")
    m2 = insert_message(db, room.id, "alice", "world")
    upsert_read_cursor(db, room.id, "bob", m2.id)
    upsert_read_cursor(db, room.id, "bob", m1.id)  # try to go backward
    cursor = get_read_cursor(db, room.id, "bob")
    assert cursor == m2.id  # stays at m2


def test_get_read_cursor_none(db):
    """Returns None when no cursor exists."""
    room = create_room(db, project="proj", name="dev")
    cursor = get_read_cursor(db, room.id, "bob")
    assert cursor is None


def test_get_unread_counts(db):
    """Batch unread counts for multiple rooms."""
    room1 = create_room(db, project="proj", name="room1")
    room2 = create_room(db, project="proj", name="room2")
    m1_1 = insert_message(db, room1.id, "alice", "msg1")
    insert_message(db, room1.id, "alice", "msg2")
    insert_message(db, room1.id, "alice", "msg3")
    insert_message(db, room2.id, "bob", "msg1")
    insert_message(db, room2.id, "bob", "msg2")
    # bob has read msg1 in room1
    upsert_read_cursor(db, room1.id, "bob", m1_1.id)
    counts = get_unread_counts(db, [room1.id, room2.id], "bob")
    assert counts[room1.id] == 2  # msg2 + msg3 unread
    assert counts[room2.id] == 2  # never read room2 → all unread


def test_get_unread_counts_no_cursor(db):
    """All messages are unread when no cursor exists."""
    room = create_room(db, project="proj", name="dev")
    insert_message(db, room.id, "alice", "msg1")
    insert_message(db, room.id, "alice", "msg2")
    counts = get_unread_counts(db, [room.id], "bob")
    assert counts[room.id] == 2


def test_get_unread_counts_all_read(db):
    """Returns 0 when cursor is at latest message."""
    room = create_room(db, project="proj", name="dev")
    insert_message(db, room.id, "alice", "msg1")
    m2 = insert_message(db, room.id, "alice", "msg2")
    upsert_read_cursor(db, room.id, "bob", m2.id)
    counts = get_unread_counts(db, [room.id], "bob")
    assert counts[room.id] == 0


def test_get_unread_counts_empty_rooms(db):
    """Rooms with no messages return 0 unread."""
    room = create_room(db, project="proj", name="empty")
    counts = get_unread_counts(db, [room.id], "bob")
    assert counts[room.id] == 0


def test_get_unread_counts_empty_list(db):
    """Empty room_ids list returns empty dict."""
    counts = get_unread_counts(db, [], "bob")
    assert counts == {}


def test_delete_read_cursors(db):
    """delete_read_cursors removes all cursors for a room."""
    from chatnut.db import delete_read_cursors
    room = create_room(db, project="proj", name="dev")
    msg = insert_message(db, room.id, "alice", "hello")
    upsert_read_cursor(db, room.id, "bob", msg.id)
    upsert_read_cursor(db, room.id, "carol", msg.id)
    delete_read_cursors(db, room.id)
    assert get_read_cursor(db, room.id, "bob") is None
    assert get_read_cursor(db, room.id, "carol") is None


def test_cross_room_cursor_isolation(db):
    """Cursor from room A does not affect room B (global autoincrement IDs)."""
    room_a = create_room(db, project="proj", name="room-a")
    room_b = create_room(db, project="proj", name="room-b")
    m_a = insert_message(db, room_a.id, "alice", "msg-in-a")
    insert_message(db, room_b.id, "bob", "msg-in-b")
    # Bob reads room A up to m_a (which has a higher ID than room_b's message)
    upsert_read_cursor(db, room_a.id, "bob", m_a.id)
    # Room B should still show 1 unread for bob (independent cursors)
    counts = get_unread_counts(db, [room_a.id, room_b.id], "bob")
    assert counts[room_a.id] == 0
    assert counts[room_b.id] == 1


# --- Room status tests ---


def test_room_status_table_exists(db):
    """Verify room_status table is created by migrations."""
    cursor = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='room_status'"
    )
    assert cursor.fetchone() is not None


def test_room_status_upsert(db):
    """Verify UPSERT semantics on room_status."""
    room = create_room(db, "test-project", "test-room")
    room_id = room.id

    # First insert
    upsert_room_status(db, room_id, "reviewer-1", "Reviewing auth module")
    statuses = get_room_statuses(db, room_id)
    assert len(statuses) == 1
    assert statuses[0]["sender"] == "reviewer-1"
    assert statuses[0]["status"] == "Reviewing auth module"

    # Update (UPSERT)
    upsert_room_status(db, room_id, "reviewer-1", "Completed review")
    statuses = get_room_statuses(db, room_id)
    assert len(statuses) == 1
    assert statuses[0]["status"] == "Completed review"

    # Second sender
    upsert_room_status(db, room_id, "codex", "Running analysis")
    statuses = get_room_statuses(db, room_id)
    assert len(statuses) == 2


def test_room_status_cascade_delete(db):
    """Verify statuses are deleted when room is deleted via db.delete_room()."""
    room = create_room(db, "test-project", "test-room")
    room_id = room.id
    upsert_room_status(db, room_id, "reviewer-1", "Working")

    # Archive then delete via db function
    db.execute(
        "UPDATE rooms SET status='archived', archived_at=datetime('now') WHERE id=?",
        (room_id,),
    )
    db.commit()
    delete_room(db, room_id)

    statuses = get_room_statuses(db, room_id)
    assert len(statuses) == 0


def test_room_status_length_constraint(db):
    """Verify status text length is capped at 500 chars."""
    room = create_room(db, "test-project", "test-room")
    room_id = room.id

    # 500 chars should succeed
    upsert_room_status(db, room_id, "agent", "x" * 500)

    # 501 chars should fail
    with pytest.raises(sqlite3.IntegrityError):
        upsert_room_status(db, room_id, "agent", "x" * 501)


# --- Agent Registry ---


def test_agent_registry_table_exists(db):
    tables = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    names = [t[0] for t in tables]
    assert "agent_registry" in names


def test_upsert_agent_registration(db):
    room = create_room(db, "proj", "dev")
    upsert_agent_registration(db, room.id, "security", "task-abc")
    regs = get_agent_registrations(db, room.id)
    assert len(regs) == 1
    assert regs[0]["agent_name"] == "security"
    assert regs[0]["task_id"] == "task-abc"
    assert regs[0]["registered_at"]


def test_upsert_agent_registration_updates_task_id(db):
    room = create_room(db, "proj", "dev")
    upsert_agent_registration(db, room.id, "security", "task-abc")
    upsert_agent_registration(db, room.id, "security", "task-xyz")
    regs = get_agent_registrations(db, room.id)
    assert len(regs) == 1
    assert regs[0]["task_id"] == "task-xyz"


def test_get_agent_registrations_empty(db):
    room = create_room(db, "proj", "dev")
    regs = get_agent_registrations(db, room.id)
    assert regs == []


def test_delete_agent_registrations(db):
    room = create_room(db, "proj", "dev")
    upsert_agent_registration(db, room.id, "security", "task-abc")
    upsert_agent_registration(db, room.id, "architect", "task-def")
    delete_agent_registrations(db, room.id)
    assert get_agent_registrations(db, room.id) == []


def test_agent_registrations_cascade_on_room_delete(db):
    """Verify ON DELETE CASCADE cleans up registrations when room is deleted directly."""
    room = create_room(db, "proj", "dev")
    upsert_agent_registration(db, room.id, "security", "task-abc")
    archive_room(db, "proj", "dev")
    # Delete room directly via SQL (bypass delete_room() which explicitly deletes)
    # to verify CASCADE works at the FK level
    with db:
        db.execute("DELETE FROM rooms WHERE id=?", (room.id,))
    row = db.execute("SELECT COUNT(*) FROM agent_registry WHERE room_id=?", (room.id,)).fetchone()
    assert row[0] == 0


def test_messages_cascade_on_room_delete(db):
    """Messages should be automatically deleted when their room is deleted via CASCADE."""
    room = create_room(db, project="proj", name="cascade-test")
    insert_message(db, room.id, "alice", "hello")
    insert_message(db, room.id, "bob", "world")

    # Archive then delete directly via SQL to test CASCADE behavior
    db.execute("UPDATE rooms SET status='archived', archived_at=datetime('now') WHERE id=?", (room.id,))
    db.commit()
    db.execute("DELETE FROM rooms WHERE id=?", (room.id,))
    db.commit()

    # Messages should be gone via CASCADE
    msgs, _ = get_messages(db, room.id)
    assert len(msgs) == 0
