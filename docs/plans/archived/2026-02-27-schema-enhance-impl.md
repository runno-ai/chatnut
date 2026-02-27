# Schema Enhancement + Unified FastAPI Server Implementation Plan

## Context

The team-chat-mcp project currently has a minimal schema (rooms keyed by name, no project/branch metadata), a separate Bun/TS server for the web UI that reads JSONL files, and an MCP server running via stdio. We need to unify into a single FastAPI process, enhance the schema with project/branch/metadata, and add sidebar filtering + search to the React SPA.

## Goal

Single FastAPI process serving MCP tools (HTTP transport) + REST/SSE web endpoints + static React build, with enhanced schema supporting project/branch scoping, and sidebar filters + search in the FE.

## Architecture

Single FastAPI app mounts FastMCP at `/mcp/` via `http_app()` + `combine_lifespans()`. REST endpoints at `/api/`, SSE streams at `/api/stream/`, static React build at `/*`. Shared `ChatService` instance used by both MCP tools and web routes. SQLite with WAL mode for concurrent access.

## Affected Areas

- Backend: `app/be/team_chat_mcp/` — models, db, service, mcp tools, new FastAPI app + routes
- Frontend: `app/fe/src/` — types, hooks, Sidebar component, App component
- Config: `pyproject.toml`, `CLAUDE.md`, `DESIGN.md`

## Key Files

- `app/be/team_chat_mcp/db.py` — Core: schema migration, all queries updated for UUID rooms + project scoping
- `app/be/team_chat_mcp/app.py` — New: FastAPI app mounting MCP + routes + static serving
- `app/be/team_chat_mcp/routes.py` — New: REST + SSE endpoints for web UI
- `app/fe/src/components/Sidebar.tsx` — Core: filter dropdowns + search box
- `app/fe/src/hooks/useChatrooms.ts` — Core: updated for new API shape with project/branch filters

## Reusable Utilities

- `fastmcp.utilities.lifespan:combine_lifespans()` — Merge FastAPI + MCP lifespans
- `app/be/team_chat_mcp/service.py:ChatService` — Enhanced, shared between MCP + REST
- `app/fe/src/utils/roleColors.ts:getRoleColor()` — Unchanged, used in sidebar

---

## Tasks

### Task 1: Enhanced Models

**Files:**
- Modify: `app/be/team_chat_mcp/models.py`
- Modify: `app/be/tests/test_models.py`

**Step 1: Write the failing test**

```python
# tests/test_models.py
"""Tests for Room and Message dataclasses."""

from team_chat_mcp.models import Room, Message


def test_room_to_dict():
    room = Room(
        id="abc-123",
        name="dev",
        project="team-chat-mcp",
        branch="main",
        description="Development room",
        status="live",
        created_at="2026-01-01T00:00:00+00:00",
        archived_at=None,
        metadata=None,
    )
    d = room.to_dict()
    assert d["id"] == "abc-123"
    assert d["name"] == "dev"
    assert d["project"] == "team-chat-mcp"
    assert d["branch"] == "main"
    assert d["description"] == "Development room"
    assert d["status"] == "live"
    assert d["archived_at"] is None
    assert d["metadata"] is None


def test_room_to_dict_minimal():
    room = Room(
        id="abc-123",
        name="dev",
        project="my-project",
        branch=None,
        description=None,
        status="live",
        created_at="2026-01-01T00:00:00+00:00",
        archived_at=None,
        metadata=None,
    )
    d = room.to_dict()
    assert d["branch"] is None
    assert d["description"] is None


def test_message_to_dict():
    msg = Message(
        id=1,
        room_id="abc-123",
        sender="alice",
        content="hello",
        message_type="message",
        created_at="2026-01-01T00:00:00+00:00",
        metadata=None,
    )
    d = msg.to_dict()
    assert d["id"] == 1
    assert d["room_id"] == "abc-123"
    assert d["sender"] == "alice"
    assert d["content"] == "hello"
    assert d["message_type"] == "message"
    assert d["metadata"] is None


def test_message_system_type():
    msg = Message(
        id=2,
        room_id="abc-123",
        sender="system",
        content="Room created",
        message_type="system",
        created_at="2026-01-01T00:00:00+00:00",
        metadata='{"event": "room_created"}',
    )
    d = msg.to_dict()
    assert d["message_type"] == "system"
    assert d["metadata"] == '{"event": "room_created"}'
```

**Step 2: Run test — expect FAIL**
```bash
cd app/be && uv run pytest tests/test_models.py -xvs
```
Expected: `TypeError` — Room/Message constructors don't accept new fields yet.

**Step 3: Implement minimal code**

```python
# team_chat_mcp/models.py
"""Dataclasses for Room and Message."""

from dataclasses import dataclass, asdict


@dataclass
class Room:
    id: str
    name: str
    project: str
    branch: str | None
    description: str | None
    status: str                # 'live' | 'archived'
    created_at: str
    archived_at: str | None
    metadata: str | None       # JSON blob

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Message:
    id: int
    room_id: str
    sender: str
    content: str
    message_type: str          # 'message' | 'system'
    created_at: str
    metadata: str | None       # JSON blob

    def to_dict(self) -> dict:
        return asdict(self)
```

**Step 4: Run test — expect PASS**
```bash
cd app/be && uv run pytest tests/test_models.py -xvs
```

**Step 5: Commit**
```bash
git add app/be/team_chat_mcp/models.py app/be/tests/test_models.py
git commit -m "feat: enhance Room and Message models with project, branch, metadata"
```

---

### Task 2: Enhanced DB Layer

**Files:**
- Modify: `app/be/team_chat_mcp/db.py`
- Modify: `app/be/tests/conftest.py`
- Modify: `app/be/tests/test_db.py`

**Step 1: Write the failing test**

```python
# tests/conftest.py
"""Shared test fixtures."""

import pytest
from team_chat_mcp.db import init_db


@pytest.fixture
def db():
    """In-memory SQLite database for testing."""
    conn = init_db(":memory:")
    yield conn
    conn.close()
```

```python
# tests/test_db.py
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
```

**Step 2: Run test — expect FAIL**
```bash
cd app/be && uv run pytest tests/test_db.py -xvs
```
Expected: `ImportError` — new functions don't exist yet.

**Step 3: Implement minimal code**

```python
# team_chat_mcp/db.py
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


def get_room_stats(conn: sqlite3.Connection, room_id: str) -> dict:
    """Get message stats for a room without fetching all messages."""
    row = conn.execute(
        "SELECT COUNT(*), MAX(id) FROM messages WHERE room_id=?",
        (room_id,),
    ).fetchone()
    message_count = row[0]
    max_id = row[1]

    last_msg = None
    last_ts = None
    if max_id:
        last_row = conn.execute(
            "SELECT content, created_at FROM messages WHERE id=?", (max_id,)
        ).fetchone()
        if last_row:
            last_msg = last_row[0][:80]
            last_ts = last_row[1]

    # Role counts (only 'message' type, not 'system')
    role_rows = conn.execute(
        "SELECT sender, COUNT(*) FROM messages WHERE room_id=? AND message_type='message' GROUP BY sender",
        (room_id,),
    ).fetchall()
    role_counts = {row[0]: row[1] for row in role_rows}

    return {
        "message_count": message_count,
        "last_message_id": max_id,
        "last_message_content": last_msg,
        "last_message_ts": last_ts,
        "role_counts": role_counts,
    }


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

    # Search message content — return distinct rooms with match count
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
    msg_query += " GROUP BY m.room_id LIMIT ?"
    msg_params.append(limit)
    msg_rows = conn.execute(msg_query, msg_params).fetchall()
    message_rooms = [{"room_id": row[0], "match_count": row[1]} for row in msg_rows]

    return {"rooms": matching_rooms, "message_rooms": message_rooms}
```

**Step 4: Run test — expect PASS**
```bash
cd app/be && uv run pytest tests/test_db.py -xvs
```

**Step 5: Commit**
```bash
git add app/be/team_chat_mcp/db.py app/be/tests/conftest.py app/be/tests/test_db.py
git commit -m "feat: enhanced DB layer with UUID rooms, project scoping, search"
```

---

### Task 3: Enhanced ChatService

**Files:**
- Modify: `app/be/team_chat_mcp/service.py`
- Modify: `app/be/tests/test_service.py`

**Step 1: Write the failing test**

```python
# tests/test_service.py
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
```

**Step 2: Run test — expect FAIL**
```bash
cd app/be && uv run pytest tests/test_service.py -xvs
```
Expected: `TypeError` — ChatService methods don't accept project parameter yet.

**Step 3: Implement minimal code**

```python
# team_chat_mcp/service.py
"""ChatService — all business logic for team chatrooms."""

import sqlite3

from team_chat_mcp.db import (
    create_room,
    get_room,
    get_room_by_id,
    list_rooms as db_list_rooms,
    list_projects as db_list_projects,
    archive_room as db_archive_room,
    insert_message,
    get_messages as db_get_messages,
    delete_messages,
    search_rooms_and_messages,
    get_room_stats as db_get_room_stats,
)


VALID_ROOM_STATUSES = {"live", "archived", "all"}


class ChatService:
    def __init__(self, db_conn: sqlite3.Connection):
        self.db = db_conn

    def init_room(
        self,
        project: str,
        name: str,
        branch: str | None = None,
        description: str | None = None,
    ) -> dict:
        room = create_room(self.db, project=project, name=name, branch=branch, description=description)
        return room.to_dict()

    def post_message(
        self,
        project: str,
        room: str,
        sender: str,
        content: str,
        message_type: str = "message",
    ) -> dict:
        room_obj = create_room(self.db, project=project, name=room)
        if room_obj.status == "archived":
            raise ValueError(f"Room '{room}' in project '{project}' is archived — cannot post messages")
        msg = insert_message(self.db, room_obj.id, sender, content, message_type=message_type)
        return msg.to_dict()

    def read_messages(
        self,
        project: str,
        room: str,
        since_id: int | None = None,
        limit: int = 100,
        message_type: str | None = None,
    ) -> dict:
        room_obj = get_room(self.db, project=project, name=room)
        if room_obj is None:
            return {"messages": [], "has_more": False}
        messages, has_more = db_get_messages(
            self.db, room_obj.id, since_id=since_id, limit=limit, message_type=message_type
        )
        return {
            "messages": [m.to_dict() for m in messages],
            "has_more": has_more,
        }

    def read_messages_by_room_id(
        self,
        room_id: str,
        since_id: int | None = None,
        limit: int = 100,
        message_type: str | None = None,
    ) -> dict:
        messages, has_more = db_get_messages(
            self.db, room_id, since_id=since_id, limit=limit, message_type=message_type
        )
        return {
            "messages": [m.to_dict() for m in messages],
            "has_more": has_more,
        }

    def get_room_stats(self, room_id: str) -> dict:
        return db_get_room_stats(self.db, room_id)

    def list_rooms(self, status: str = "live", project: str | None = None, branch: str | None = None) -> dict:
        if status not in VALID_ROOM_STATUSES:
            raise ValueError(f"Invalid status '{status}' — must be one of {VALID_ROOM_STATUSES}")
        rooms = db_list_rooms(self.db, status=status, project=project, branch=branch)
        return {"rooms": [r.to_dict() for r in rooms]}

    def list_projects(self) -> dict:
        projects = db_list_projects(self.db)
        return {"projects": projects}

    def archive_room(self, project: str, name: str) -> dict:
        room = db_archive_room(self.db, project=project, name=name)
        if room is None:
            raise ValueError(f"Room '{name}' in project '{project}' not found")
        return {"name": room.name, "project": room.project, "archived_at": room.archived_at}

    def clear_room(self, project: str, name: str) -> dict:
        room_obj = get_room(self.db, project=project, name=name)
        if room_obj is None:
            raise ValueError(f"Room '{name}' in project '{project}' not found")
        count = delete_messages(self.db, room_obj.id)
        return {"name": name, "project": project, "deleted_count": count}

    def search(self, query: str, project: str | None = None) -> dict:
        result = search_rooms_and_messages(self.db, query, project=project)
        return {
            "rooms": [r.to_dict() for r in result["rooms"]],
            "message_rooms": result["message_rooms"],
        }
```

**Step 4: Run test — expect PASS**
```bash
cd app/be && uv run pytest tests/test_service.py -xvs
```

**Step 5: Commit**
```bash
git add app/be/team_chat_mcp/service.py app/be/tests/test_service.py
git commit -m "feat: enhance ChatService with project scoping, search, message types"
```

---

### Task 4: MCP Tools (mcp.py)

**Files:**
- Create: `app/be/team_chat_mcp/mcp.py`
- Delete: `app/be/team_chat_mcp/server.py`
- Create: `app/be/tests/test_mcp.py`

**Step 1: Write the smoke test**

```python
# tests/test_mcp.py
"""Smoke tests for MCP tool registration."""

from team_chat_mcp.mcp import mcp


def test_all_tools_registered():
    """Verify all expected MCP tools are registered."""
    tool_names = {t.name for t in mcp._tool_manager.list_tools()}
    expected = {"ping", "init_room", "post_message", "read_messages", "list_rooms", "archive_room", "clear_room", "search", "list_projects"}
    assert expected.issubset(tool_names), f"Missing tools: {expected - tool_names}"
```

**Step 2: Implement** — module-level tool definitions (no factory pattern)

```python
# team_chat_mcp/mcp.py
"""FastMCP tool definitions — thin wrappers over ChatService."""

import os
from functools import lru_cache

from fastmcp import FastMCP

from team_chat_mcp.db import init_db
from team_chat_mcp.service import ChatService

mcp = FastMCP("team-chat")

DB_PATH = os.path.expanduser(os.environ.get("CHAT_DB_PATH", "~/.claude/team-chat.db"))


@lru_cache(maxsize=1)
def _get_service() -> ChatService:
    db_conn = init_db(DB_PATH)
    return ChatService(db_conn)


@mcp.tool()
def ping() -> dict:
    """Health check — returns DB path and status."""
    return {"db_path": DB_PATH, "status": "ok"}


@mcp.tool()
def init_room(
    project: str,
    name: str,
    branch: str | None = None,
    description: str | None = None,
) -> dict:
    """Create a new chatroom. Idempotent — returns existing room if already created."""
    return _get_service().init_room(project, name, branch=branch, description=description)


@mcp.tool()
def post_message(
    project: str,
    room: str,
    sender: str,
    content: str,
    message_type: str = "message",
) -> dict:
    """Post a message to a room. Auto-creates room if missing. Rejects posts to archived rooms."""
    return _get_service().post_message(project, room, sender, content, message_type=message_type)


@mcp.tool()
def read_messages(
    project: str,
    room: str,
    since_id: int | None = None,
    limit: int = 100,
    message_type: str | None = None,
) -> dict:
    """Read messages from a room. Use since_id for incremental polling. Default limit 100."""
    return _get_service().read_messages(project, room, since_id=since_id, limit=limit, message_type=message_type)


@mcp.tool()
def list_rooms(project: str | None = None, status: str = "live") -> dict:
    """List rooms by status. Options: 'live' (default), 'archived', 'all'. Filter by project."""
    return _get_service().list_rooms(status=status, project=project)


@mcp.tool()
def list_projects() -> dict:
    """List all distinct project names across all rooms."""
    return _get_service().list_projects()


@mcp.tool()
def archive_room(project: str, name: str) -> dict:
    """Archive a room. Sets status to 'archived', keeps all messages."""
    return _get_service().archive_room(project, name)


@mcp.tool()
def clear_room(project: str, name: str) -> dict:
    """Delete all messages in a room. Keeps the room record."""
    return _get_service().clear_room(project, name)


@mcp.tool()
def search(query: str, project: str | None = None) -> dict:
    """Search room names and message content. Optionally filter by project."""
    return _get_service().search(query, project=project)
```

**Step 3: Run test — expect PASS**
```bash
cd app/be && uv run pytest tests/test_mcp.py -xvs
```

**Step 4: Commit**
```bash
git rm app/be/team_chat_mcp/server.py
git add app/be/team_chat_mcp/mcp.py app/be/tests/test_mcp.py
git commit -m "feat: new MCP tools with project scoping, replaces server.py"
```

---

### Task 5: FastAPI App + Routes

**Files:**
- Create: `app/be/team_chat_mcp/app.py`
- Create: `app/be/team_chat_mcp/routes.py`
- Modify: `app/be/pyproject.toml`

**Step 1: Update dependencies**

Add `fastapi`, `uvicorn`, `sse-starlette` to `pyproject.toml`:

```toml
[project]
name = "team-chat-mcp"
version = "0.2.0"
description = "MCP server for agent team chatrooms with SQLite backend"
requires-python = ">=3.12"
dependencies = [
    "fastmcp>=2.0.0",
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.34.0",
    "sse-starlette>=2.0.0",
]

[project.optional-dependencies]
test = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "httpx>=0.28.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

**Step 2: Implement routes.py**

```python
# team_chat_mcp/routes.py
"""REST + SSE endpoints for the web UI."""

import asyncio
import json

from fastapi import APIRouter, Header, Query, Request
from sse_starlette.sse import EventSourceResponse


router = APIRouter(prefix="/api")

POLL_INTERVAL = 0.5
KEEPALIVE_INTERVAL = 15  # seconds between keepalive comments


def create_router(get_service) -> APIRouter:
    """Create API router with the provided service factory."""

    @router.get("/status")
    def status():
        return {"status": "ok"}

    @router.get("/projects")
    def projects():
        return get_service().list_projects()

    @router.get("/chatrooms")
    def chatrooms(
        project: str | None = None,
        branch: str | None = None,
        status: str = "live",
    ):
        return get_service().list_rooms(status=status, project=project, branch=branch)

    @router.get("/chatrooms/{room_id}/messages")
    def room_messages(
        room_id: str,
        since_id: int | None = None,
        limit: int = 100,
        message_type: str | None = None,
    ):
        return get_service().read_messages_by_room_id(
            room_id, since_id=since_id, limit=limit, message_type=message_type
        )

    @router.get("/search")
    def search(q: str, project: str | None = None):
        return get_service().search(q, project=project)

    @router.get("/stream/chatrooms")
    async def stream_chatrooms(
        request: Request,
        project: str | None = None,
        branch: str | None = None,
    ):
        svc = get_service()

        async def event_generator():
            last_hash = ""
            keepalive_counter = 0
            while True:
                if await request.is_disconnected():
                    break
                result = svc.list_rooms(status="all", project=project, branch=branch)
                rooms = result["rooms"]
                active = [r for r in rooms if r["status"] == "live"]
                archived = [r for r in rooms if r["status"] == "archived"]

                # Enrich with message stats via efficient DB queries (no full message fetch)
                for room_dict in active + archived:
                    stats = svc.get_room_stats(room_dict["id"])
                    room_dict["messageCount"] = stats["message_count"]
                    room_dict["lastMessage"] = stats["last_message_content"]
                    room_dict["lastMessageTs"] = stats["last_message_ts"]
                    room_dict["roleCounts"] = stats["role_counts"]

                # Detect changes via content hash
                payload = json.dumps({"active": active, "archived": archived}, sort_keys=True)
                content_hash = str(hash(payload))
                if content_hash != last_hash:
                    last_hash = content_hash
                    keepalive_counter = 0
                    yield {"data": payload}
                else:
                    keepalive_counter += 1
                    # Send keepalive comment to prevent proxy/browser timeouts
                    if keepalive_counter >= int(KEEPALIVE_INTERVAL / POLL_INTERVAL):
                        keepalive_counter = 0
                        yield {"comment": "keepalive"}

                await asyncio.sleep(POLL_INTERVAL)

        return EventSourceResponse(event_generator())

    @router.get("/stream/messages")
    async def stream_messages(
        request: Request,
        room_id: str = Query(...),
        last_event_id: str | None = Header(None, alias="Last-Event-Id"),
    ):
        svc = get_service()

        async def event_generator():
            # Honor Last-Event-Id for SSE reconnection
            last_id = int(last_event_id) if last_event_id else 0
            keepalive_counter = 0

            if last_id == 0:
                # Send full history first
                result = svc.read_messages_by_room_id(room_id, limit=1000)
                for msg in result["messages"]:
                    yield {"id": str(msg["id"]), "data": json.dumps(msg)}
                    last_id = msg["id"]

            # Then poll for new messages
            while True:
                if await request.is_disconnected():
                    break
                result = svc.read_messages_by_room_id(room_id, since_id=last_id, limit=100)
                if result["messages"]:
                    keepalive_counter = 0
                    for msg in result["messages"]:
                        yield {"id": str(msg["id"]), "data": json.dumps(msg)}
                        last_id = msg["id"]
                else:
                    keepalive_counter += 1
                    if keepalive_counter >= int(KEEPALIVE_INTERVAL / POLL_INTERVAL):
                        keepalive_counter = 0
                        yield {"comment": "keepalive"}
                await asyncio.sleep(POLL_INTERVAL)

        return EventSourceResponse(event_generator())

    return router
```

**Step 3: Implement app.py**

```python
# team_chat_mcp/app.py
"""FastAPI application — mounts MCP + REST/SSE routes + static file serving."""

import os
from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastmcp.utilities.lifespan import combine_lifespans

from team_chat_mcp.db import init_db
from team_chat_mcp.service import ChatService
from team_chat_mcp.mcp import mcp
from team_chat_mcp.routes import create_router

DB_PATH = os.path.expanduser(os.environ.get("CHAT_DB_PATH", "~/.claude/team-chat.db"))
STATIC_DIR = os.environ.get("STATIC_DIR", os.path.join(os.path.dirname(__file__), "../../fe/dist"))


@lru_cache(maxsize=1)
def _get_service() -> ChatService:
    db_conn = init_db(DB_PATH)
    return ChatService(db_conn)


# Get MCP ASGI sub-app — path="" so MCP handles at mount root, not double-prefixed
mcp_app = mcp.http_app(path="", transport="streamable-http")


@asynccontextmanager
async def app_lifespan(app):
    # Ensure service is initialized at startup
    _get_service()
    yield


app = FastAPI(
    title="Team Chat",
    lifespan=combine_lifespans(app_lifespan, mcp_app.lifespan),
)

# Mount MCP at /mcp — path="" in http_app() + mount("/mcp") = /mcp (not /mcp/mcp)
app.mount("/mcp", mcp_app)

# Mount API routes
api_router = create_router(_get_service)
app.include_router(api_router)


# Serve React SPA — static files + fallback to index.html
@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    static_dir = os.path.abspath(STATIC_DIR)
    file_path = os.path.join(static_dir, full_path)
    if os.path.isfile(file_path):
        return FileResponse(file_path)
    index_path = os.path.join(static_dir, "index.html")
    if os.path.isfile(index_path):
        return FileResponse(index_path)
    return {"error": "Frontend not built. Run: cd app/fe && bun run build"}
```

**Step 4: Write route tests**

```python
# tests/test_routes.py
"""Tests for REST + SSE endpoints."""

import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from team_chat_mcp.service import ChatService
from team_chat_mcp.routes import create_router


@pytest.fixture
def app(db):
    """FastAPI test app with routes wired to in-memory DB."""
    svc = ChatService(db)
    test_app = FastAPI()
    router = create_router(lambda: svc)
    test_app.include_router(router)
    return test_app


@pytest.fixture
def client(app):
    return TestClient(app)


def test_status(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_projects_empty(client):
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    assert resp.json()["projects"] == []


def test_projects_with_rooms(client, db):
    svc = ChatService(db)
    svc.init_room("proj-a", "dev")
    svc.init_room("proj-b", "staging")
    resp = client.get("/api/projects")
    assert set(resp.json()["projects"]) == {"proj-a", "proj-b"}


def test_chatrooms_list(client, db):
    svc = ChatService(db)
    svc.init_room("proj", "dev")
    svc.init_room("proj", "staging")
    resp = client.get("/api/chatrooms", params={"project": "proj"})
    assert resp.status_code == 200
    assert len(resp.json()["rooms"]) == 2


def test_chatrooms_filter_by_branch(client, db):
    svc = ChatService(db)
    svc.init_room("proj", "dev", branch="main")
    svc.init_room("proj", "staging", branch="feat/auth")
    resp = client.get("/api/chatrooms", params={"project": "proj", "branch": "main"})
    rooms = resp.json()["rooms"]
    assert len(rooms) == 1
    assert rooms[0]["name"] == "dev"


def test_room_messages(client, db):
    svc = ChatService(db)
    svc.post_message("proj", "dev", "alice", "hello")
    svc.post_message("proj", "dev", "bob", "world")
    rooms = svc.list_rooms(project="proj")
    room_id = rooms["rooms"][0]["id"]
    resp = client.get(f"/api/chatrooms/{room_id}/messages")
    assert resp.status_code == 200
    msgs = resp.json()["messages"]
    assert len(msgs) == 2
    assert msgs[0]["sender"] == "alice"


def test_room_messages_since_id(client, db):
    svc = ChatService(db)
    m1 = svc.post_message("proj", "dev", "alice", "first")
    svc.post_message("proj", "dev", "bob", "second")
    rooms = svc.list_rooms(project="proj")
    room_id = rooms["rooms"][0]["id"]
    resp = client.get(f"/api/chatrooms/{room_id}/messages", params={"since_id": m1["id"]})
    msgs = resp.json()["messages"]
    assert len(msgs) == 1
    assert msgs[0]["content"] == "second"


def test_search(client, db):
    svc = ChatService(db)
    svc.post_message("proj", "planning", "alice", "discuss auth feature")
    resp = client.get("/api/search", params={"q": "auth", "project": "proj"})
    assert resp.status_code == 200
    assert len(resp.json()["message_rooms"]) == 1


def test_stream_messages_initial_history(client, db):
    svc = ChatService(db)
    svc.post_message("proj", "dev", "alice", "hello")
    svc.post_message("proj", "dev", "bob", "world")
    rooms = svc.list_rooms(project="proj")
    room_id = rooms["rooms"][0]["id"]

    with client.stream("GET", f"/api/stream/messages?room_id={room_id}") as resp:
        assert resp.status_code == 200
        events = []
        for line in resp.iter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))
            if len(events) >= 2:
                break
        assert len(events) == 2
        assert events[0]["sender"] == "alice"
        assert events[1]["sender"] == "bob"


def test_stream_messages_last_event_id(client, db):
    svc = ChatService(db)
    m1 = svc.post_message("proj", "dev", "alice", "first")
    svc.post_message("proj", "dev", "bob", "second")
    rooms = svc.list_rooms(project="proj")
    room_id = rooms["rooms"][0]["id"]

    with client.stream(
        "GET",
        f"/api/stream/messages?room_id={room_id}",
        headers={"Last-Event-Id": str(m1["id"])},
    ) as resp:
        assert resp.status_code == 200
        events = []
        for line in resp.iter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))
            if len(events) >= 1:
                break
        assert len(events) == 1
        assert events[0]["content"] == "second"
```

**Step 5: Run tests — expect PASS**
```bash
cd app/be && uv run pytest tests/test_routes.py -xvs
```

**Step 6: Commit**
```bash
git add app/be/team_chat_mcp/app.py app/be/team_chat_mcp/routes.py app/be/pyproject.toml app/be/tests/test_routes.py
git commit -m "feat: FastAPI app with MCP mounting, REST/SSE routes, static serving"
```

---

### Task 6: Integration Tests

**Files:**
- Modify: `app/be/tests/test_integration.py`

**Step 1: Write tests**

```python
# tests/test_integration.py
"""Integration tests — verify full tool flows end-to-end via ChatService."""

import pytest
from team_chat_mcp.service import ChatService


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


def test_auto_create_room_on_post(db):
    """post_message should auto-create room if it doesn't exist."""
    svc = ChatService(db)
    svc.post_message("proj", "auto-room", "alice", "first message")

    rooms = svc.list_rooms(project="proj")
    names = [r["name"] for r in rooms["rooms"]]
    assert "auto-room" in names


def test_clear_room_preserves_room(db):
    """clear_room deletes messages but keeps the room record."""
    svc = ChatService(db)
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
```

**Step 2: Run test — expect PASS**
```bash
cd app/be && uv run pytest tests/ -xvs
```

**Step 3: Commit**
```bash
git add app/be/tests/test_integration.py
git commit -m "test: enhanced integration tests for project scoping, search, message types"
```

---

### Task 7: FE Types + Hooks

**Files:**
- Modify: `app/fe/src/types.ts`
- Modify: `app/fe/src/hooks/useChatrooms.ts`
- Modify: `app/fe/src/hooks/useSSE.ts`

**Step 1: Implement types.ts**

```typescript
// src/types.ts
export interface ChatMessage {
  id: number;
  room_id: string;
  sender: string;
  content: string;
  message_type: "message" | "system";
  created_at: string;
  metadata: string | null;
}

export interface ChatroomInfo {
  id: string;
  name: string;
  project: string;
  branch: string | null;
  description: string | null;
  status: "live" | "archived";
  created_at: string;
  archived_at: string | null;
  metadata: string | null;
  messageCount?: number;
  lastMessage?: string;
  lastMessageTs?: string;
  roleCounts?: Record<string, number>;
}

export interface ChatroomsResponse {
  active: ChatroomInfo[];
  archived: ChatroomInfo[];
}

export interface SearchResult {
  rooms: ChatroomInfo[];
  message_rooms: Array<{ room_id: string; match_count: number }>;
}
```

**Step 2: Implement useChatrooms.ts**

```typescript
// src/hooks/useChatrooms.ts
import { useState, useEffect, useRef } from "react";
import type { ChatroomInfo, ChatroomsResponse } from "../types";

export function useChatrooms(project?: string, branch?: string) {
  const [active, setActive] = useState<ChatroomInfo[]>([]);
  const [archived, setArchived] = useState<ChatroomInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const retryRef = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    let es: EventSource | null = null;
    let closed = false;

    function connect() {
      if (closed) return;
      const params = new URLSearchParams();
      if (project) params.set("project", project);
      if (branch) params.set("branch", branch);
      const qs = params.toString();
      es = new EventSource(`/api/stream/chatrooms${qs ? `?${qs}` : ""}`);

      es.onmessage = (e) => {
        try {
          const data: ChatroomsResponse = JSON.parse(e.data);
          setActive(data.active);
          setArchived(data.archived);
          setLoading(false);
        } catch {}
      };

      es.onerror = () => {
        es?.close();
        if (!closed) {
          retryRef.current = setTimeout(connect, 3000);
        }
      };
    }

    connect();

    return () => {
      closed = true;
      es?.close();
      if (retryRef.current) clearTimeout(retryRef.current);
    };
  }, [project, branch]);

  return { active, archived, loading };
}
```

**Step 3: Implement useSSE.ts**

```typescript
// src/hooks/useSSE.ts
import { useState, useEffect, useRef } from "react";
import type { ChatMessage } from "../types";

type ConnectionStatus = "connecting" | "connected" | "disconnected";

export function useSSE(roomId: string | null) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [connectionStatus, setConnectionStatus] =
    useState<ConnectionStatus>("connecting");
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!roomId) {
      setMessages([]);
      setConnectionStatus("disconnected");
      return;
    }

    setMessages([]);
    setConnectionStatus("connecting");

    const es = new EventSource(
      `/api/stream/messages?room_id=${encodeURIComponent(roomId)}`
    );
    esRef.current = es;

    es.onopen = () => {
      setConnectionStatus("connected");
    };

    es.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data) as ChatMessage;
        setMessages((prev) => [...prev, msg]);
      } catch {}
    };

    es.addEventListener("reset", () => {
      setMessages([]);
    });

    es.onerror = () => {
      setConnectionStatus("disconnected");
    };

    return () => {
      es.close();
      esRef.current = null;
    };
  }, [roomId]);

  return { messages, connectionStatus };
}
```

**Step 4: Commit**
```bash
git add app/fe/src/types.ts app/fe/src/hooks/useChatrooms.ts app/fe/src/hooks/useSSE.ts
git commit -m "feat: update FE types and hooks for project-scoped API"
```

---

### Task 8: FE Sidebar Filters + Search

**Files:**
- Modify: `app/fe/src/components/Sidebar.tsx`
- Modify: `app/fe/src/App.tsx`
- Create: `app/fe/src/hooks/useSearch.ts`
- Create: `app/fe/src/hooks/useProjects.ts`

**Step 1: Implement useProjects.ts**

Derives project list from SSE chatroom data (always fresh, no stale one-shot fetch):

```typescript
// src/hooks/useProjects.ts
import { useMemo } from "react";
import type { ChatroomInfo } from "../types";

export function useProjects(active: ChatroomInfo[], archived: ChatroomInfo[]) {
  return useMemo(() => {
    const all = [...active, ...archived];
    return [...new Set(all.map((r) => r.project))].sort();
  }, [active, archived]);
}
```

**Step 2: Implement useSearch.ts**

```typescript
// src/hooks/useSearch.ts
import { useState, useEffect, useRef } from "react";
import type { SearchResult } from "../types";

export function useSearch(query: string, project?: string) {
  const [result, setResult] = useState<SearchResult | null>(null);
  const [loading, setLoading] = useState(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    if (!query || query.length < 2) {
      setResult(null);
      setLoading(false);
      return;
    }

    setLoading(true);
    if (timeoutRef.current) clearTimeout(timeoutRef.current);

    timeoutRef.current = setTimeout(() => {
      const params = new URLSearchParams({ q: query });
      if (project) params.set("project", project);
      fetch(`/api/search?${params}`)
        .then((res) => res.json())
        .then((data) => {
          setResult(data);
          setLoading(false);
        })
        .catch(() => {
          setResult(null);
          setLoading(false);
        });
    }, 300);

    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, [query, project]);

  return { result, loading };
}
```

**Step 3: Update Sidebar.tsx**

```tsx
// src/components/Sidebar.tsx
import { useState } from "react";
import type { ChatroomInfo, SearchResult } from "../types";
import { getRoleColor } from "../utils/roleColors";

interface SidebarProps {
  active: ChatroomInfo[];
  archived: ChatroomInfo[];
  loading: boolean;
  selectedRoom: string | null;
  collapsed: boolean;
  width: number;
  projects: string[];
  selectedProject: string | null;
  selectedBranch: string | null;
  searchQuery: string;
  searchResult: SearchResult | null;
  searchLoading: boolean;
  onSelectRoom: (roomId: string) => void;
  onToggleCollapse: () => void;
  onSelectProject: (project: string | null) => void;
  onSelectBranch: (branch: string | null) => void;
  onSearchChange: (query: string) => void;
}

function formatRelativeTime(ts?: string): string {
  if (!ts) return "";
  try {
    const date = new Date(ts);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMin = Math.floor(diffMs / 60000);
    const diffHr = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMin < 1) return "just now";
    if (diffMin < 60) return `${diffMin}m`;
    if (diffHr < 24) return `${diffHr}h`;
    if (diffDays < 7) return `${diffDays}d`;
    return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  } catch {
    return "";
  }
}

export function Sidebar({
  active,
  archived,
  loading,
  selectedRoom,
  collapsed,
  width,
  projects,
  selectedProject,
  selectedBranch,
  searchQuery,
  searchResult,
  searchLoading,
  onSelectRoom,
  onToggleCollapse,
  onSelectProject,
  onSelectBranch,
  onSearchChange,
}: SidebarProps) {
  if (collapsed) {
    return (
      <div className="w-10 bg-gray-900 border-r border-gray-800 flex flex-col items-center pt-3">
        <button
          onClick={onToggleCollapse}
          className="text-gray-400 hover:text-gray-200 p-1"
          title="Expand sidebar"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
            <path d="M6 3l5 5-5 5V3z" />
          </svg>
        </button>
      </div>
    );
  }

  // Derive available branches from all rooms (active + archived)
  const branches = [...new Set([...active, ...archived].map((r) => r.branch).filter(Boolean))] as string[];

  // Sort active: by last message time (newest first)
  const sortedActive = [...active].sort((a, b) => {
    return (b.lastMessageTs ?? "").localeCompare(a.lastMessageTs ?? "");
  });

  // Search result highlighting
  const searchRoomIds = new Set(searchResult?.rooms?.map((r) => r.id) ?? []);
  const messageMatchRoomIds = new Map(
    searchResult?.message_rooms?.map((mr) => [mr.room_id, mr.match_count]) ?? []
  );

  const isSearching = searchQuery.length >= 2;

  // Filter rooms by search if active
  const filteredActive = isSearching
    ? sortedActive.filter((r) => searchRoomIds.has(r.id) || messageMatchRoomIds.has(r.id))
    : sortedActive;

  return (
    <div className="bg-gray-900 border-r border-gray-800 flex flex-col shrink-0" style={{ width }}>
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-3 border-b border-gray-800">
        <span className="text-sm font-semibold text-gray-300">Chatrooms</span>
        <button
          onClick={onToggleCollapse}
          className="text-gray-400 hover:text-gray-200 p-1"
          title="Collapse sidebar"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
            <path d="M10 3l-5 5 5 5V3z" />
          </svg>
        </button>
      </div>

      {/* Filters */}
      <div className="px-3 py-2 space-y-2 border-b border-gray-800">
        <div className="flex gap-2">
          <select
            value={selectedProject ?? ""}
            onChange={(e) => {
              onSelectProject(e.target.value || null);
              onSelectBranch(null);
            }}
            className="flex-1 bg-gray-800 text-gray-300 text-xs rounded px-2 py-1.5 border border-gray-700 focus:border-blue-500 focus:outline-none"
          >
            <option value="">All projects</option>
            {projects.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
          <select
            value={selectedBranch ?? ""}
            onChange={(e) => onSelectBranch(e.target.value || null)}
            disabled={!selectedProject}
            className="flex-1 bg-gray-800 text-gray-300 text-xs rounded px-2 py-1.5 border border-gray-700 focus:border-blue-500 focus:outline-none disabled:opacity-40"
          >
            <option value="">All branches</option>
            {branches.map((b) => (
              <option key={b} value={b}>{b}</option>
            ))}
          </select>
        </div>
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="Search rooms & messages..."
          className="w-full bg-gray-800 text-gray-300 text-xs rounded px-2 py-1.5 border border-gray-700 focus:border-blue-500 focus:outline-none placeholder-gray-600"
        />
      </div>

      <div className="flex-1 overflow-y-auto">
        {loading && (
          <div className="px-3 py-4 text-sm text-gray-500">Loading...</div>
        )}

        {isSearching && searchLoading && (
          <div className="px-3 py-4 text-sm text-gray-500">Searching...</div>
        )}

        {isSearching && !searchLoading && filteredActive.length === 0 && (
          <div className="px-3 py-4 text-sm text-gray-500">No results found.</div>
        )}

        {/* Live */}
        {filteredActive.length > 0 && (
          <div className="px-2 pt-3">
            <div className="px-2 pb-1 text-xs font-semibold text-gray-500 uppercase tracking-wider">
              Live
            </div>
            {filteredActive.map((room) => (
              <RoomItem
                key={room.id}
                room={room}
                isLive
                isSelected={selectedRoom === room.id}
                matchCount={messageMatchRoomIds.get(room.id)}
                showProject={!selectedProject}
                onClick={() => onSelectRoom(room.id)}
              />
            ))}
          </div>
        )}

        {/* Archived */}
        {!isSearching && archived.length > 0 && (
          <ArchivedSection
            archived={archived}
            selectedRoom={selectedRoom}
            showProject={!selectedProject}
            onSelectRoom={onSelectRoom}
          />
        )}
      </div>
    </div>
  );
}

const ARCHIVE_PAGE_SIZE = 10;

function ArchivedSection({
  archived,
  selectedRoom,
  showProject,
  onSelectRoom,
}: {
  archived: ChatroomInfo[];
  selectedRoom: string | null;
  showProject: boolean;
  onSelectRoom: (roomId: string) => void;
}) {
  const [showCount, setShowCount] = useState(ARCHIVE_PAGE_SIZE);
  const visible = archived.slice(0, showCount);
  const remaining = archived.length - showCount;

  return (
    <div className="px-2 pt-3">
      <div className="px-2 pb-1 text-xs font-semibold text-gray-500 uppercase tracking-wider">
        Archived
      </div>
      {visible.map((room) => (
        <RoomItem
          key={room.id}
          room={room}
          isSelected={selectedRoom === room.id}
          showProject={showProject}
          onClick={() => onSelectRoom(room.id)}
        />
      ))}
      {remaining > 0 && (
        <button
          onClick={() => setShowCount((c) => c + ARCHIVE_PAGE_SIZE)}
          className="w-full text-center text-xs text-gray-500 hover:text-gray-300 py-2 transition-colors"
        >
          Show more ({remaining})
        </button>
      )}
    </div>
  );
}

function RoomItem({
  room,
  isLive,
  isSelected,
  matchCount,
  showProject,
  onClick,
}: {
  room: ChatroomInfo;
  isLive?: boolean;
  isSelected: boolean;
  matchCount?: number;
  showProject?: boolean;
  onClick: () => void;
}) {
  const timeStr = formatRelativeTime(room.lastMessageTs);

  const roles = room.roleCounts
    ? Object.entries(room.roleCounts).sort(([, a], [, b]) => b - a)
    : [];

  return (
    <button
      onClick={onClick}
      className={`relative w-full text-left px-2 py-2 rounded-md mb-0.5 transition-colors ${
        isSelected
          ? "bg-gray-800 text-gray-100"
          : "text-gray-400 hover:bg-gray-800/50 hover:text-gray-200"
      }`}
    >
      {isSelected && (
        <span className="absolute left-0 top-1.5 bottom-1.5 w-[3px] rounded-full bg-blue-500" />
      )}
      <div className="flex items-center gap-2">
        {isLive && (
          <span className="relative flex h-2 w-2 shrink-0">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500" />
          </span>
        )}
        <span className="text-sm font-medium truncate">{room.name}</span>
        {matchCount && (
          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-yellow-500/20 text-yellow-400">
            {matchCount} match{matchCount > 1 ? "es" : ""}
          </span>
        )}
        <span className="text-xs text-gray-600 ml-auto shrink-0">
          {timeStr}
        </span>
      </div>
      {(showProject || room.branch) && (
        <div className="flex gap-1 mt-0.5 pl-4">
          {showProject && (
            <span className="text-[10px] text-gray-600">{room.project}</span>
          )}
          {room.branch && (
            <span className="text-[10px] text-gray-600">/{room.branch}</span>
          )}
        </div>
      )}
      {roles.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-1 pl-4">
          <span className="inline-flex items-center text-[10px] leading-tight px-1.5 py-0.5 rounded-full bg-gray-700/50 text-gray-400">
            {room.messageCount}
          </span>
          {roles.map(([role, count]) => (
            <span
              key={role}
              className="inline-flex items-center gap-0.5 text-[10px] leading-tight px-1.5 py-0.5 rounded-full"
              style={{
                backgroundColor: getRoleColor(role) + "12",
                color: getRoleColor(role) + "90",
              }}
            >
              {role}
              <span className="opacity-60">{count}</span>
            </span>
          ))}
        </div>
      )}
    </button>
  );
}
```

**Step 4: Update App.tsx**

```tsx
// src/App.tsx
import "./index.css";
import { useState, useMemo, useCallback, useRef } from "react";
import { Sidebar } from "./components/Sidebar";
import { ChatView } from "./components/ChatView";
import { useChatrooms } from "./hooks/useChatrooms";
import { useProjects } from "./hooks/useProjects";
import { useSearch } from "./hooks/useSearch";

const SIDEBAR_MIN = 200;
const SIDEBAR_MAX = 500;
const SIDEBAR_DEFAULT = 280;

export default function App() {
  const [selectedProject, setSelectedProject] = useState<string | null>(null);
  const [selectedBranch, setSelectedBranch] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");

  const { active, archived, loading } = useChatrooms(
    selectedProject ?? undefined,
    selectedBranch ?? undefined
  );
  const projects = useProjects(active, archived);
  const { result: searchResult, loading: searchLoading } = useSearch(
    searchQuery,
    selectedProject ?? undefined
  );

  const [selectedRoom, setSelectedRoom] = useState<string | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(SIDEBAR_DEFAULT);
  const dragging = useRef(false);

  const onDragStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    dragging.current = true;
    const onMove = (ev: MouseEvent) => {
      if (!dragging.current) return;
      setSidebarWidth(Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, ev.clientX)));
    };
    const onUp = () => {
      dragging.current = false;
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  }, []);

  // Active rooms are live-streamable via SSE, archived are static
  const activeIds = useMemo(
    () => new Set(active.map((r) => r.id)),
    [active]
  );
  const isLive = selectedRoom ? activeIds.has(selectedRoom) : false;

  return (
    <div className="flex h-screen bg-gray-950 text-gray-100 overflow-hidden">
      <Sidebar
        active={active}
        archived={archived}
        loading={loading}
        selectedRoom={selectedRoom}
        collapsed={sidebarCollapsed}
        width={sidebarWidth}
        projects={projects}
        selectedProject={selectedProject}
        selectedBranch={selectedBranch}
        searchQuery={searchQuery}
        searchResult={searchResult}
        searchLoading={searchLoading}
        onSelectRoom={setSelectedRoom}
        onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
        onSelectProject={setSelectedProject}
        onSelectBranch={setSelectedBranch}
        onSearchChange={setSearchQuery}
      />
      {/* Resize handle */}
      {!sidebarCollapsed && (
        <div
          onMouseDown={onDragStart}
          className="w-1 cursor-col-resize hover:bg-blue-500/40 active:bg-blue-500/60 transition-colors shrink-0"
        />
      )}
      <ChatView
        room={selectedRoom}
        roomName={
          [...active, ...archived].find((r) => r.id === selectedRoom)?.name ?? selectedRoom
        }
        isLive={isLive}
      />
    </div>
  );
}
```

**Step 5: Update Message.tsx** — rename fields from old JSONL format to new API format

The current Message.tsx uses `message.from`, `message.msg`, `message.ts` (JSONL field names).
The new API returns `message.sender`, `message.content`, `message.created_at`.

```tsx
// src/components/Message.tsx — updated field references
// Replace throughout:
//   message.from  → message.sender
//   message.msg   → message.content
//   message.ts    → message.created_at

export function Message({ message }: MessageProps) {
  const color = getRoleColor(message.sender);
  const mentions = useMemo(() => extractMentions(message.content), [message.content]);

  return (
    <div
      className="rounded-lg bg-gray-900 px-4 py-3 my-2"
      style={{ borderLeft: `3px solid ${color}` }}
    >
      {/* Header */}
      <div className="flex items-center gap-2 mb-1.5 flex-wrap">
        <span className="text-sm font-semibold" style={{ color }}>
          {message.sender}
        </span>
        <span className="text-xs text-gray-600">
          {formatTimestamp(message.created_at)}
        </span>
        {mentions.length > 0 && (
          <>
            <span className="text-xs text-gray-700">mentions</span>
            {mentions.map((m) => (
              <MentionChip key={m} name={m} />
            ))}
          </>
        )}
      </div>

      {/* Body */}
      <div className="text-base text-gray-300 prose prose-invert prose-base max-w-none [&_pre]:bg-gray-950 [&_pre]:rounded [&_pre]:p-2 [&_pre]:my-1 [&_code]:text-emerald-400 [&_code]:text-sm [&_p]:my-1 [&_ul]:my-1 [&_ol]:my-1 [&_li]:my-0 [&_h1]:text-lg [&_h2]:text-base [&_h3]:text-base [&_table]:text-sm [&_th]:px-2 [&_td]:px-2">
        <MarkdownRenderer content={message.content} />
      </div>
    </div>
  );
}
```

**Step 6: Update ChatView.tsx** — fix header, message key, and archived fetch response shape

```tsx
// src/components/ChatView.tsx — key changes:

// 1. Props: add roomName
interface ChatViewProps {
  room: string | null;    // UUID
  roomName: string | null; // display name (from sidebar)
  isLive: boolean;
}

// 2. Header: show roomName instead of raw UUID
<h2 className="text-sm font-semibold text-gray-200">{roomName}</h2>

// 3. Archived fetch: response is { messages: [...], has_more } not bare array
.then((data) => {
    setStaticMessages(data.messages || []);
})

// 4. Message key: use msg.id (stable integer) instead of msg.ts-index
{messages.map((msg) => (
    <Message key={msg.id} message={msg} />
))}
```

The `room` prop value is now a UUID (opaque string), so the existing
`/api/chatrooms/${room}/messages` URL works without changes.

**Step 7: Update MarkdownRenderer.tsx** — update extractMentions to handle new field name

No changes needed — `extractMentions()` takes a string parameter, not a message object.
The call site change in Message.tsx (`message.content` instead of `message.msg`) is sufficient.

**Step 8: Commit**
```bash
git add app/fe/src/
git commit -m "feat: sidebar filters (project/branch) and search box"
```

---

### Task 9: Delete Bun Server + Cleanup

**Files:**
- Delete: `app/fe/server/` (entire directory)
- Modify: `app/fe/package.json` — remove `"serve"` script
- Modify: `app/fe/vite.config.ts` — update dev proxy to FastAPI port

**Step 1: Delete server directory**

```bash
rm -rf app/fe/server/
```

**Step 2: Update package.json**

Remove the `"serve"` script (no more Bun server):

```json
{
  "name": "team-chat-ui",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build"
  },
  "dependencies": {
    "@tailwindcss/typography": "^0.5.19",
    "@tailwindcss/vite": "^4.1.18",
    "react": "^19.1.0",
    "react-dom": "^19.1.0",
    "react-markdown": "^10.1.0",
    "rehype-highlight": "^7.0.2",
    "remark-gfm": "^4.0.1",
    "tailwindcss": "^4.1.18"
  },
  "devDependencies": {
    "@vitejs/plugin-react": "^4.5.2",
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "typescript": "~5.8.2",
    "vite": "^6.2.0",
    "vite-plugin-singlefile": "^2.0.3"
  }
}
```

**Step 3: Update vite.config.ts**

Update dev proxy to point to FastAPI (port 8000 default):

```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { viteSingleFile } from "vite-plugin-singlefile";
import path from "path";

export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/mcp": "http://localhost:8000",
    },
  },
  plugins: [react(), tailwindcss(), viteSingleFile()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  build: {
    target: "esnext",
    assetsInlineLimit: 100000000,
    chunkSizeWarningLimit: 100000000,
    cssCodeSplit: false,
    rollupOptions: {
      output: { inlineDynamicImports: true },
    },
  },
});
```

**Step 4: Remove @types/bun** (no longer needed)

```bash
cd app/fe && bun remove @types/bun
```

**Step 5: Commit**
```bash
git add -A app/fe/
git commit -m "refactor: delete Bun server, proxy to FastAPI"
```

---

### Phase 10: Documentation Update

**Files:**
- Modify: `CLAUDE.md`
- Modify: `DESIGN.md`

Update CLAUDE.md to reflect:
- New project structure (`app/be/`, `app/fe/`, no root-level Python)
- New schema with `id`, `project`, `branch`, `metadata`, `message_type`
- FastAPI as unified server (MCP + REST + SSE + static)
- New commands: `uvicorn team_chat_mcp.app:app`
- Updated MCP registration (HTTP transport)
- Updated tool signatures with `project` parameter
- Removed Bun server references

Update DESIGN.md to reflect:
- Unified FastAPI architecture (no separate Bun server)
- Enhanced schema
- Sidebar filters + search

---

## Verification

```bash
# Backend tests
cd app/be && uv sync --extra test && uv run pytest -xvs

# Frontend build
cd app/fe && bun install && bun run build

# Start unified server
cd app/be && uv run uvicorn team_chat_mcp.app:app --port 8000

# Verify MCP endpoint
curl -X POST http://localhost:8000/mcp/ -H "Content-Type: application/json"

# Verify REST endpoint
curl http://localhost:8000/api/status

# Verify SSE endpoint
curl http://localhost:8000/api/stream/chatrooms

# Verify static serving
curl http://localhost:8000/
```

Expected: All tests pass, server starts, MCP responds, API responds, frontend loads.

## AI Review Findings

| Severity | Source | Finding | Action |
|----------|--------|---------|--------|
| Critical | Architect, QA | SSE `stream_chatrooms` O(rooms*messages) polling — fetches all messages every 500ms | Fixed: Added `get_room_stats()` DB helper using `COUNT(*)`/`MAX(id)` queries |
| Critical | Backend Dev, Architect | Message.tsx uses `.from`/`.msg`/`.ts` (old JSONL fields) — breaks with new API | Fixed: Updated Task 8 with field renames to `.sender`/`.content`/`.created_at` |
| Critical | QA, Codex | LIKE wildcard injection — `%` and `_` not escaped in search queries | Fixed: Added `_escape_like()` helper with `ESCAPE '\'` clauses |
| Critical | QA | No route tests — REST/SSE endpoints untested | Fixed: Added `test_routes.py` in Task 5 with httpx/TestClient |
| Critical | Architect | No MCP tool tests — smoke test missing | Fixed: Added `test_mcp.py` smoke test verifying all tools registered |
| Critical | Backend Dev | routes.py bypasses service layer — direct db imports | Fixed: Routes now use `svc.read_messages_by_room_id()` and `svc.get_room_stats()` |
| Critical | Architect, Gemini | Double MCP path prefix `/mcp/mcp` — `http_app(path="/mcp")` + `mount("/mcp")` | Fixed: Changed to `http_app(path="")` + `mount("/mcp")` |
| Critical | Architect | `register_tools` factory pattern unnecessary — module-level decorators simpler | Fixed: Task 4 rewritten with module-level `@mcp.tool()` definitions |
| Critical | Frontend Dev | SSE no Last-Event-Id support — full re-fetch on reconnect | Fixed: `stream_messages` reads `Last-Event-Id` header, resumes from that ID |
| Warning | QA | No SSE keepalive — proxy/browser may timeout idle connections | Fixed: Added 15s keepalive comments in both SSE endpoints |
| Warning | Frontend Dev | Branch dropdown only derives from active rooms — misses archived | Fixed: Derives from `[...active, ...archived]` |
| Warning | Frontend Dev | `useProjects` one-shot fetch goes stale | Fixed: Changed to `useMemo` deriving from SSE chatroom data |
| Warning | Architect | `list_rooms` MCP tool missing `branch` filter | Fixed: Added `branch` param to `list_rooms()` in db + service layers |
| Warning | Backend Dev | `list_projects` missing from MCP tools | Fixed: Added `list_projects` tool to mcp.py |
| Warning | Backend Dev, QA | ChatView header shows raw UUID instead of room name | Fixed: Added `roomName` prop, App.tsx looks up name from chatroom data |
| Suggestion | Gemini | Add `current` field or default room selection strategy | Deferred: FE can auto-select first room from SSE data if no room selected |
