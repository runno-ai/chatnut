"""Tests for database layer."""

import sqlite3
import pytest
from team_chat_mcp.db import (
    init_db,
    create_room,
    get_room,
    get_room_by_id,
    list_rooms,
    list_projects,
    archive_room,
    insert_message,
    get_messages,
    delete_messages,
    search_rooms_and_messages,
    get_room_stats,
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


def test_get_room_stats(db):
    room = create_room(db, project="proj", name="dev")
    insert_message(db, room.id, "alice", "hello")
    insert_message(db, room.id, "bob", "world")
    insert_message(db, room.id, "alice", "again")
    insert_message(db, room.id, "system", "event", message_type="system")

    stats = get_room_stats(db, room.id)
    assert stats["message_count"] == 4
    assert stats["last_message_id"] is not None
    assert stats["last_message_ts"] is not None
    assert stats["last_message_content"][:5] == "event"
    assert stats["role_counts"]["alice"] == 2
    assert stats["role_counts"]["bob"] == 1


def test_list_rooms_filter_by_branch(db):
    create_room(db, project="proj", name="dev", branch="main")
    create_room(db, project="proj", name="staging", branch="feat/auth")
    rooms = list_rooms(db, branch="main")
    assert len(rooms) == 1
    assert rooms[0].name == "dev"
