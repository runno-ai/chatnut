"""Tests for the database layer."""

import pytest
from team_chat_mcp.db import (
    init_db,
    create_room,
    get_room,
    list_rooms,
    archive_room,
    insert_message,
    get_messages,
    delete_messages,
)
from team_chat_mcp.models import Room, Message


def test_init_db_creates_tables(db):
    cursor = db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [row[0] for row in cursor.fetchall()]
    assert "messages" in tables
    assert "rooms" in tables


def test_create_room(db):
    room = create_room(db, "dev")
    assert room.name == "dev"
    assert room.status == "live"
    assert room.archived_at is None


def test_create_room_idempotent(db):
    r1 = create_room(db, "dev")
    r2 = create_room(db, "dev")
    assert r1.name == r2.name
    assert r1.created_at == r2.created_at


def test_get_room(db):
    create_room(db, "dev")
    room = get_room(db, "dev")
    assert room is not None
    assert room.name == "dev"


def test_get_room_missing(db):
    assert get_room(db, "nope") is None


def test_list_rooms_default_live(db):
    create_room(db, "dev")
    create_room(db, "staging")
    archive_room(db, "staging")
    rooms = list_rooms(db)
    assert len(rooms) == 1
    assert rooms[0].name == "dev"


def test_list_rooms_all(db):
    create_room(db, "dev")
    create_room(db, "staging")
    archive_room(db, "staging")
    rooms = list_rooms(db, status="all")
    assert len(rooms) == 2


def test_list_rooms_archived(db):
    create_room(db, "dev")
    create_room(db, "staging")
    archive_room(db, "staging")
    rooms = list_rooms(db, status="archived")
    assert len(rooms) == 1
    assert rooms[0].name == "staging"


def test_archive_room(db):
    create_room(db, "dev")
    room = archive_room(db, "dev")
    assert room.status == "archived"
    assert room.archived_at is not None


def test_archive_room_not_found(db):
    room = archive_room(db, "nope")
    assert room is None


def test_insert_and_get_messages(db):
    create_room(db, "dev")
    msg = insert_message(db, "dev", "alice", "hello")
    assert msg.id is not None
    assert msg.room == "dev"
    assert msg.sender == "alice"
    assert msg.content == "hello"

    messages, has_more = get_messages(db, "dev")
    assert len(messages) == 1
    assert messages[0].content == "hello"
    assert has_more is False


def test_get_messages_since_id(db):
    create_room(db, "dev")
    m1 = insert_message(db, "dev", "alice", "first")
    m2 = insert_message(db, "dev", "bob", "second")
    m3 = insert_message(db, "dev", "alice", "third")

    messages, has_more = get_messages(db, "dev", since_id=m1.id)
    assert len(messages) == 2
    assert messages[0].content == "second"
    assert messages[1].content == "third"


def test_get_messages_limit(db):
    create_room(db, "dev")
    for i in range(5):
        insert_message(db, "dev", "alice", f"msg-{i}")

    messages, has_more = get_messages(db, "dev", limit=3)
    assert len(messages) == 3
    assert has_more is True
    assert messages[0].content == "msg-0"


def test_get_messages_limit_exact(db):
    """When message count equals limit, has_more should be False."""
    create_room(db, "dev")
    for i in range(3):
        insert_message(db, "dev", "alice", f"msg-{i}")

    messages, has_more = get_messages(db, "dev", limit=3)
    assert len(messages) == 3
    assert has_more is False


def test_delete_messages(db):
    create_room(db, "dev")
    insert_message(db, "dev", "alice", "hello")
    insert_message(db, "dev", "bob", "world")

    count = delete_messages(db, "dev")
    assert count == 2

    messages, _ = get_messages(db, "dev")
    assert len(messages) == 0


def test_delete_messages_empty_room(db):
    create_room(db, "dev")
    count = delete_messages(db, "dev")
    assert count == 0


def test_insert_message_fk_enforced(db):
    """Foreign key constraint prevents orphan messages."""
    import sqlite3 as _sqlite3
    with pytest.raises(_sqlite3.IntegrityError):
        insert_message(db, "nonexistent-room", "alice", "orphan message")


def test_archive_room_already_archived(db):
    create_room(db, "dev")
    archive_room(db, "dev")
    result = archive_room(db, "dev")
    assert result is None  # Already archived, AND status='live' doesn't match
