"""SQLite schema, migrations, and queries for team chat."""

import os
import sqlite3
from datetime import datetime, timezone

from team_chat_mcp.models import Room, Message

SCHEMA = """
CREATE TABLE IF NOT EXISTS rooms (
    name TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'live',
    created_at TEXT NOT NULL,
    archived_at TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room TEXT NOT NULL REFERENCES rooms(name),
    sender TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_room ON messages(room, id);
"""

ROOM_COLUMNS = ["name", "status", "created_at", "archived_at"]
MSG_COLUMNS = ["id", "room", "sender", "content", "created_at"]


def init_db(db_path: str) -> sqlite3.Connection:
    if db_path != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    return conn


def _row_to_room(row: tuple) -> Room:
    return Room(**dict(zip(ROOM_COLUMNS, row)))


def _row_to_message(row: tuple) -> Message:
    return Message(**dict(zip(MSG_COLUMNS, row)))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_room(conn: sqlite3.Connection, name: str) -> Room:
    now = _now()
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO rooms (name, status, created_at) VALUES (?, 'live', ?)",
            (name, now),
        )
    row = conn.execute(
        "SELECT name, status, created_at, archived_at FROM rooms WHERE name=?",
        (name,),
    ).fetchone()
    return _row_to_room(row)


def get_room(conn: sqlite3.Connection, name: str) -> Room | None:
    row = conn.execute(
        "SELECT name, status, created_at, archived_at FROM rooms WHERE name=?",
        (name,),
    ).fetchone()
    return _row_to_room(row) if row else None


def list_rooms(conn: sqlite3.Connection, status: str = "live") -> list[Room]:
    if status == "all":
        cursor = conn.execute(
            "SELECT name, status, created_at, archived_at FROM rooms ORDER BY created_at"
        )
    else:
        cursor = conn.execute(
            "SELECT name, status, created_at, archived_at FROM rooms WHERE status=? ORDER BY created_at",
            (status,),
        )
    return [_row_to_room(row) for row in cursor.fetchall()]


def archive_room(conn: sqlite3.Connection, name: str) -> Room | None:
    now = _now()
    with conn:
        cursor = conn.execute(
            "UPDATE rooms SET status='archived', archived_at=? WHERE name=? AND status='live'",
            (now, name),
        )
    if cursor.rowcount == 0:
        return None
    return get_room(conn, name)


def insert_message(conn: sqlite3.Connection, room: str, sender: str, content: str) -> Message:
    now = _now()
    with conn:
        cursor = conn.execute(
            "INSERT INTO messages (room, sender, content, created_at) VALUES (?, ?, ?, ?)",
            (room, sender, content, now),
        )
    row = conn.execute(
        "SELECT id, room, sender, content, created_at FROM messages WHERE id=?",
        (cursor.lastrowid,),
    ).fetchone()
    return _row_to_message(row)


def get_messages(
    conn: sqlite3.Connection,
    room: str,
    since_id: int | None = None,
    limit: int = 100,
) -> tuple[list[Message], bool]:
    limit = max(1, min(limit, 1000))
    query = "SELECT id, room, sender, content, created_at FROM messages WHERE room=?"
    params: list = [room]

    if since_id is not None:
        query += " AND id > ?"
        params.append(since_id)

    query += " ORDER BY id ASC LIMIT ?"
    params.append(limit + 1)  # Fetch one extra to detect has_more

    cursor = conn.execute(query, params)
    rows = cursor.fetchall()

    has_more = len(rows) > limit
    messages = [_row_to_message(row) for row in rows[:limit]]
    return messages, has_more


def delete_messages(conn: sqlite3.Connection, room: str) -> int:
    with conn:
        cursor = conn.execute("DELETE FROM messages WHERE room=?", (room,))
    return cursor.rowcount
