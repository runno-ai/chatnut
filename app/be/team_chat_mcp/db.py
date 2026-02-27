"""SQLite schema, migrations, and queries for team chat."""

import os
import sqlite3
import uuid
from datetime import datetime, timezone

from team_chat_mcp.models import Room, Message

SCHEMA = """
CREATE TABLE IF NOT EXISTS rooms (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    project TEXT NOT NULL,
    branch TEXT,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'live',
    created_at TEXT NOT NULL,
    archived_at TEXT,
    metadata TEXT,
    UNIQUE(project, name)
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id TEXT NOT NULL REFERENCES rooms(id),
    sender TEXT NOT NULL,
    content TEXT NOT NULL,
    message_type TEXT NOT NULL DEFAULT 'message',
    created_at TEXT NOT NULL,
    metadata TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_room ON messages(room_id, id);
"""

ROOM_COLUMNS = ["id", "name", "project", "branch", "description", "status", "created_at", "archived_at", "metadata"]
MSG_COLUMNS = ["id", "room_id", "sender", "content", "message_type", "created_at", "metadata"]


def init_db(db_path: str) -> sqlite3.Connection:
    if db_path != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    return conn


def _row_to_room(row: tuple) -> Room:
    return Room(**dict(zip(ROOM_COLUMNS, row)))


def _row_to_message(row: tuple) -> Message:
    return Message(**dict(zip(MSG_COLUMNS, row)))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


def _room_select() -> str:
    return "SELECT " + ", ".join(ROOM_COLUMNS) + " FROM rooms"


def _msg_select() -> str:
    return "SELECT " + ", ".join(MSG_COLUMNS) + " FROM messages"


def create_room(
    conn: sqlite3.Connection,
    project: str,
    name: str,
    branch: str | None = None,
    description: str | None = None,
    metadata: str | None = None,
) -> Room:
    now = _now()
    room_id = _new_id()
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO rooms (id, name, project, branch, description, status, created_at, metadata) VALUES (?, ?, ?, ?, ?, 'live', ?, ?)",
            (room_id, name, project, branch, description, now, metadata),
        )
    row = conn.execute(
        _room_select() + " WHERE project=? AND name=?",
        (project, name),
    ).fetchone()
    return _row_to_room(row)


def get_room(conn: sqlite3.Connection, project: str, name: str) -> Room | None:
    row = conn.execute(
        _room_select() + " WHERE project=? AND name=?",
        (project, name),
    ).fetchone()
    return _row_to_room(row) if row else None


def get_room_by_id(conn: sqlite3.Connection, room_id: str) -> Room | None:
    row = conn.execute(
        _room_select() + " WHERE id=?",
        (room_id,),
    ).fetchone()
    return _row_to_room(row) if row else None


def _escape_like(query: str) -> str:
    """Escape SQL LIKE wildcards in user input."""
    return query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def list_rooms(
    conn: sqlite3.Connection,
    status: str = "live",
    project: str | None = None,
    branch: str | None = None,
) -> list[Room]:
    query = _room_select()
    params: list = []
    conditions = []

    if status != "all":
        conditions.append("status=?")
        params.append(status)
    if project is not None:
        conditions.append("project=?")
        params.append(project)
    if branch is not None:
        conditions.append("branch=?")
        params.append(branch)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY created_at"

    cursor = conn.execute(query, params)
    return [_row_to_room(row) for row in cursor.fetchall()]


def list_projects(conn: sqlite3.Connection) -> list[str]:
    cursor = conn.execute("SELECT DISTINCT project FROM rooms ORDER BY project")
    return [row[0] for row in cursor.fetchall()]


def archive_room(conn: sqlite3.Connection, project: str, name: str) -> Room | None:
    now = _now()
    with conn:
        cursor = conn.execute(
            "UPDATE rooms SET status='archived', archived_at=? WHERE project=? AND name=? AND status='live'",
            (now, project, name),
        )
    if cursor.rowcount == 0:
        return None
    return get_room(conn, project, name)


def insert_message(
    conn: sqlite3.Connection,
    room_id: str,
    sender: str,
    content: str,
    message_type: str = "message",
    metadata: str | None = None,
) -> Message:
    now = _now()
    with conn:
        cursor = conn.execute(
            "INSERT INTO messages (room_id, sender, content, message_type, created_at, metadata) VALUES (?, ?, ?, ?, ?, ?)",
            (room_id, sender, content, message_type, now, metadata),
        )
    row = conn.execute(
        _msg_select() + " WHERE id=?",
        (cursor.lastrowid,),
    ).fetchone()
    return _row_to_message(row)


def get_messages(
    conn: sqlite3.Connection,
    room_id: str,
    since_id: int | None = None,
    limit: int = 100,
    message_type: str | None = None,
) -> tuple[list[Message], bool]:
    limit = max(1, min(limit, 1000))
    query = _msg_select() + " WHERE room_id=?"
    params: list = [room_id]

    if since_id is not None:
        query += " AND id > ?"
        params.append(since_id)

    if message_type is not None:
        query += " AND message_type = ?"
        params.append(message_type)

    query += " ORDER BY id ASC LIMIT ?"
    params.append(limit + 1)

    cursor = conn.execute(query, params)
    rows = cursor.fetchall()

    has_more = len(rows) > limit
    messages = [_row_to_message(row) for row in rows[:limit]]
    return messages, has_more


def delete_messages(conn: sqlite3.Connection, room_id: str) -> int:
    with conn:
        cursor = conn.execute("DELETE FROM messages WHERE room_id=?", (room_id,))
    return cursor.rowcount


def get_all_room_stats(conn: sqlite3.Connection, room_ids: list[str]) -> dict[str, dict]:
    """Get message stats for multiple rooms in batch (3 queries total, not 3N).

    Returns a dict keyed by room_id with stats:
    - message_count: total messages (all types)
    - last_message_id: MAX(id) across all types
    - last_message_content: content of last message (truncated to 80 chars)
    - last_message_ts: timestamp of last message
    - role_counts: {sender: count} for message_type='message' only

    Note: SQLite limits parameterized queries to 999 variables. For typical usage
    (< 100 rooms) this is not a concern.
    """
    if not room_ids:
        return {}

    placeholders = ",".join("?" * len(room_ids))

    # Query 1: counts and max_id per room
    count_rows = conn.execute(
        f"SELECT room_id, COUNT(*), MAX(id) FROM messages WHERE room_id IN ({placeholders}) GROUP BY room_id",
        room_ids,
    ).fetchall()
    count_map = {row[0]: {"count": row[1], "max_id": row[2]} for row in count_rows}

    # Query 2: last message content/timestamp (one max_id per room = no ambiguity)
    max_ids = [v["max_id"] for v in count_map.values() if v["max_id"] is not None]
    last_msg_map: dict[str, tuple[str, str]] = {}
    if max_ids:
        id_placeholders = ",".join("?" * len(max_ids))
        last_rows = conn.execute(
            f"SELECT room_id, content, created_at FROM messages WHERE id IN ({id_placeholders})",
            max_ids,
        ).fetchall()
        last_msg_map = {row[0]: (row[1][:80], row[2]) for row in last_rows}

    # Query 3: role counts per room (only 'message' type, excludes 'system')
    role_rows = conn.execute(
        f"SELECT room_id, sender, COUNT(*) FROM messages WHERE room_id IN ({placeholders}) AND message_type='message' GROUP BY room_id, sender",
        room_ids,
    ).fetchall()
    role_map: dict[str, dict[str, int]] = {}
    for row in role_rows:
        role_map.setdefault(row[0], {})[row[1]] = row[2]

    # Assemble results for all requested rooms (including those with no messages)
    result: dict[str, dict] = {}
    for rid in room_ids:
        counts = count_map.get(rid, {"count": 0, "max_id": None})
        last = last_msg_map.get(rid)
        result[rid] = {
            "message_count": counts["count"],
            "last_message_id": counts["max_id"],
            "last_message_content": last[0] if last else None,
            "last_message_ts": last[1] if last else None,
            "role_counts": role_map.get(rid, {}),
        }
    return result


def search_rooms_and_messages(
    conn: sqlite3.Connection,
    query: str,
    project: str | None = None,
    limit: int = 20,
) -> dict:
    escaped = _escape_like(query)
    like_pattern = f"%{escaped}%"

    # Search room names
    room_query = _room_select() + " WHERE name LIKE ? ESCAPE '\\'"
    room_params: list = [like_pattern]
    if project:
        room_query += " AND project=?"
        room_params.append(project)
    room_query += " LIMIT ?"
    room_params.append(limit)
    room_rows = conn.execute(room_query, room_params).fetchall()
    matching_rooms = [_row_to_room(row) for row in room_rows]

    # Search message content -- return distinct rooms with match count
    msg_query = """
        SELECT m.room_id, COUNT(*) as match_count
        FROM messages m
        JOIN rooms r ON m.room_id = r.id
        WHERE m.content LIKE ? ESCAPE '\\'
    """
    msg_params: list = [like_pattern]
    if project:
        msg_query += " AND r.project=?"
        msg_params.append(project)
    msg_query += " GROUP BY m.room_id ORDER BY match_count DESC, m.room_id ASC LIMIT ?"
    msg_params.append(limit)
    msg_rows = conn.execute(msg_query, msg_params).fetchall()
    message_rooms = [{"room_id": row[0], "match_count": row[1]} for row in msg_rows]

    return {"rooms": matching_rooms, "message_rooms": message_rooms}
