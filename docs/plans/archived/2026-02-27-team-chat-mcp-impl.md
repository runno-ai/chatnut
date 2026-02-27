# Team Chat MCP Implementation Plan

## Context

Agent teams currently use `chat.sh` (bash + JSONL) for chatroom communication. This is fragile — no queryability, shell escaping bugs, line-counting for incremental reads. We need a SQLite-backed MCP server that provides structured tooling, following the issue-tracker-mcp pattern exactly.

## Goal

Implement the team-chat MCP server: 4 source modules (`models.py`, `db.py`, `service.py`, `server.py`), test fixtures, and full test coverage for all 7 tools.

## Architecture

Three-layer stack mirroring issue-tracker-mcp: thin `@mcp.tool()` wrappers in `server.py` delegate to `ChatService` in `service.py`, which calls pure functions in `db.py`. Models are plain `@dataclass` objects. SQLite with WAL mode for concurrent reads from the web UI.

## Affected Areas

- Backend: `team_chat_mcp/` (all 4 modules)
- Tests: `tests/` (conftest.py + test file)

## Key Files

- `team_chat_mcp/models.py` — Room and Message dataclasses
- `team_chat_mcp/db.py` — Schema, init_db, all SQL queries
- `team_chat_mcp/service.py` — ChatService business logic
- `team_chat_mcp/server.py` — FastMCP app + tool definitions
- `tests/conftest.py` — In-memory DB fixture

## Reusable Utilities

- `~/issue-tracker-mcp/issue_tracker_mcp/db.py:init_db()` — Pattern for `init_db` with WAL + schema
- `~/issue-tracker-mcp/issue_tracker_mcp/server.py:_get_service()` — `@lru_cache` singleton pattern
- `~/issue-tracker-mcp/tests/conftest.py` — In-memory DB fixture pattern

---

## Tasks

### Task 1: Models (Room + Message dataclasses)

**Files:**
- Modify: `team_chat_mcp/models.py`
- Test: `tests/test_models.py`

**Step 1: Write the failing test**

```python
# tests/test_models.py
"""Tests for Room and Message dataclasses."""

from team_chat_mcp.models import Room, Message


def test_room_to_dict():
    room = Room(name="dev", status="live", created_at="2026-02-27T10:00:00+00:00", archived_at=None)
    d = room.to_dict()
    assert d == {
        "name": "dev",
        "status": "live",
        "created_at": "2026-02-27T10:00:00+00:00",
        "archived_at": None,
    }


def test_message_to_dict():
    msg = Message(id=1, room="dev", sender="architect", content="hello", created_at="2026-02-27T10:00:00+00:00")
    d = msg.to_dict()
    assert d == {
        "id": 1,
        "room": "dev",
        "sender": "architect",
        "content": "hello",
        "created_at": "2026-02-27T10:00:00+00:00",
    }
```

**Step 2: Run test — expect FAIL**
```bash
uv run pytest tests/test_models.py -xvs
```
Expected: `ImportError` — `Room` and `Message` not defined yet.

**Step 3: Implement minimal code**

```python
# team_chat_mcp/models.py
"""Dataclasses for Room and Message."""

from dataclasses import dataclass, asdict


@dataclass
class Room:
    name: str
    status: str            # 'live' | 'archived'
    created_at: str
    archived_at: str | None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Message:
    id: int
    room: str
    sender: str
    content: str
    created_at: str

    def to_dict(self) -> dict:
        return asdict(self)
```

**Step 4: Run test — expect PASS**
```bash
uv run pytest tests/test_models.py -xvs
```

**Step 5: Commit**
```bash
git add team_chat_mcp/models.py tests/test_models.py
git commit -m "feat: add Room and Message dataclasses"
```

---

### Task 2: Database layer (schema + init_db + CRUD)

**Files:**
- Modify: `team_chat_mcp/db.py`
- Create: `tests/conftest.py` (replace stub)
- Create: `tests/test_db.py`

**Step 1: Write the failing test**

```python
# tests/conftest.py
"""Shared fixtures for team-chat tests."""

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
```

**Step 2: Run test — expect FAIL**
```bash
uv run pytest tests/test_db.py -xvs
```
Expected: `ImportError` — db functions not defined yet.

**Step 3: Implement minimal code**

```python
# team_chat_mcp/db.py
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
```

**Step 4: Run test — expect PASS**
```bash
uv run pytest tests/test_db.py -xvs
```

**Step 5: Commit**
```bash
git add team_chat_mcp/db.py tests/conftest.py tests/test_db.py
git commit -m "feat: add database layer with schema and CRUD operations"
```

---

### Task 3: ChatService (business logic)

**Files:**
- Modify: `team_chat_mcp/service.py`
- Create: `tests/test_service.py`

**Step 1: Write the failing test**

```python
# tests/test_service.py
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
```

**Step 2: Run test — expect FAIL**
```bash
uv run pytest tests/test_service.py -xvs
```
Expected: `ImportError` — `ChatService` not defined yet.

**Step 3: Implement minimal code**

```python
# team_chat_mcp/service.py
"""ChatService — all business logic for team chatrooms."""

import sqlite3

from team_chat_mcp.db import (
    create_room,
    get_room,
    list_rooms as db_list_rooms,
    archive_room as db_archive_room,
    insert_message,
    get_messages as db_get_messages,
    delete_messages,
)


VALID_ROOM_STATUSES = {"live", "archived", "all"}


class ChatService:
    def __init__(self, db_conn: sqlite3.Connection):
        self.db = db_conn

    def init_room(self, name: str) -> dict:
        room = create_room(self.db, name)
        return room.to_dict()

    def post_message(self, room: str, sender: str, content: str) -> dict:
        room_obj = create_room(self.db, room)  # INSERT OR IGNORE — safe under concurrency
        if room_obj.status == "archived":
            raise ValueError(f"Room '{room}' is archived — cannot post messages")
        msg = insert_message(self.db, room, sender, content)
        return {"id": msg.id, "room": msg.room, "sender": msg.sender, "content": msg.content, "created_at": msg.created_at}

    def read_messages(self, room: str, since_id: int | None = None, limit: int = 100) -> dict:
        messages, has_more = db_get_messages(self.db, room, since_id=since_id, limit=limit)
        return {
            "messages": [m.to_dict() for m in messages],
            "has_more": has_more,
        }

    def list_rooms(self, status: str = "live") -> dict:
        if status not in VALID_ROOM_STATUSES:
            raise ValueError(f"Invalid status '{status}' — must be one of {VALID_ROOM_STATUSES}")
        rooms = db_list_rooms(self.db, status=status)
        return {"rooms": [r.to_dict() for r in rooms]}

    def archive_room(self, name: str) -> dict:
        room = db_archive_room(self.db, name)
        if room is None:
            raise ValueError(f"Room '{name}' not found")
        return {"name": room.name, "archived_at": room.archived_at}

    def clear_room(self, name: str) -> dict:
        room = get_room(self.db, name)
        if room is None:
            raise ValueError(f"Room '{name}' not found")
        count = delete_messages(self.db, name)
        return {"name": name, "deleted_count": count}
```

**Step 4: Run test — expect PASS**
```bash
uv run pytest tests/test_service.py -xvs
```

**Step 5: Commit**
```bash
git add team_chat_mcp/service.py tests/test_service.py
git commit -m "feat: add ChatService with all business logic"
```

---

### Task 4: MCP server (tool wrappers)

**Files:**
- Modify: `team_chat_mcp/server.py`

**Step 1: Write the failing test**

No separate test file for server.py — the tools are thin wrappers. The existing service tests cover all logic. We verify the server module imports cleanly.

```bash
uv run python -c "from team_chat_mcp.server import mcp; print('ok')"
```

**Step 2: Run test — expect FAIL**
```bash
uv run python -c "from team_chat_mcp.server import mcp; print(type(mcp))"
```
Expected: imports work but no tools defined (mcp object exists but has no tools registered).

**Step 3: Implement minimal code**

```python
# team_chat_mcp/server.py
"""Team Chat MCP Server — thin tool wrappers over ChatService."""

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
def init_room(name: str) -> dict:
    """Create a new chatroom. Idempotent — returns existing room if already created."""
    return _get_service().init_room(name)


@mcp.tool()
def post_message(room: str, sender: str, content: str) -> dict:
    """Post a message to a room. Auto-creates room if missing. Rejects posts to archived rooms."""
    return _get_service().post_message(room, sender, content)


@mcp.tool()
def read_messages(room: str, since_id: int | None = None, limit: int = 100) -> dict:
    """Read messages from a room. Use since_id for incremental polling. Default limit 100."""
    return _get_service().read_messages(room, since_id=since_id, limit=limit)


@mcp.tool()
def list_rooms(status: str = "live") -> dict:
    """List rooms by status. Options: 'live' (default), 'archived', 'all'."""
    return _get_service().list_rooms(status=status)


@mcp.tool()
def archive_room(name: str) -> dict:
    """Archive a room. Sets status to 'archived', keeps all messages."""
    return _get_service().archive_room(name)


@mcp.tool()
def clear_room(name: str) -> dict:
    """Delete all messages in a room. Keeps the room record."""
    return _get_service().clear_room(name)
```

**Step 4: Run test — expect PASS**
```bash
uv run python -c "from team_chat_mcp.server import mcp; print('ok')"
uv run pytest -xvs
```

**Step 5: Commit**
```bash
git add team_chat_mcp/server.py
git commit -m "feat: add MCP tool wrappers for all 7 tools"
```

---

### Task 5: Integration smoke test

**Files:**
- Create: `tests/test_integration.py`

**Step 1: Write the failing test**

```python
# tests/test_integration.py
"""Integration tests — verify full tool flows end-to-end via ChatService."""

import pytest
from team_chat_mcp.service import ChatService


def test_full_lifecycle(db):
    """Room creation -> post messages -> read -> archive -> reject post."""
    svc = ChatService(db)

    # Create room
    room = svc.init_room("integration-test")
    assert room["status"] == "live"

    # Post messages
    m1 = svc.post_message("integration-test", "alice", "hello")
    m2 = svc.post_message("integration-test", "bob", "world")

    # Read all
    result = svc.read_messages("integration-test")
    assert len(result["messages"]) == 2

    # Read incremental
    result = svc.read_messages("integration-test", since_id=m1["id"])
    assert len(result["messages"]) == 1
    assert result["messages"][0]["sender"] == "bob"

    # Archive
    archived = svc.archive_room("integration-test")
    assert archived["archived_at"] is not None

    # Verify post to archived room fails
    with pytest.raises(ValueError, match="archived"):
        svc.post_message("integration-test", "alice", "should fail")

    # Messages still readable after archive
    result = svc.read_messages("integration-test")
    assert len(result["messages"]) == 2


def test_auto_create_room_on_post(db):
    """post_message should auto-create room if it doesn't exist."""
    svc = ChatService(db)
    svc.post_message("auto-room", "alice", "first message")

    rooms = svc.list_rooms()
    names = [r["name"] for r in rooms["rooms"]]
    assert "auto-room" in names


def test_clear_room_preserves_room(db):
    """clear_room deletes messages but keeps the room record."""
    svc = ChatService(db)
    svc.post_message("clear-test", "alice", "hello")
    svc.post_message("clear-test", "bob", "world")

    result = svc.clear_room("clear-test")
    assert result["deleted_count"] == 2

    # Room still exists
    rooms = svc.list_rooms()
    names = [r["name"] for r in rooms["rooms"]]
    assert "clear-test" in names

    # No messages remain
    msgs = svc.read_messages("clear-test")
    assert len(msgs["messages"]) == 0
```

**Step 2: Run test — expect FAIL**
```bash
uv run pytest tests/test_integration.py -xvs
```
Expected: Should pass immediately since all implementation is done. If it fails, there's a bug.

**Step 3: Implement minimal code**

No new code needed — this tests the existing implementation.

**Step 4: Run test — expect PASS**
```bash
uv run pytest tests/test_integration.py -xvs
```

**Step 5: Commit**
```bash
git add tests/test_integration.py
git commit -m "test: add integration smoke tests for full lifecycle"
```

---

### Phase 6: Documentation Update

- [ ] Update `CLAUDE.md` if any commands or structure changed (verify accuracy)
- [ ] Verify `pyproject.toml` dependencies are correct (fastmcp>=2.0.0 covers 3.x)

---

## Verification

```bash
uv run pytest -xvs
```

Expected: All tests pass — models, db, service, and integration.

```bash
uv run fastmcp run team_chat_mcp/server.py
```

Expected: Server starts without errors (manual verification — press Ctrl+C to stop).

## AI Review Findings

| Severity | Source | Finding | Action |
|----------|--------|---------|--------|
| Critical | Gemini | FastMCP dispatches via anyio threads — `check_same_thread=False` required | Added to `init_db()` |
| Critical | Architect+Backend+QA | `PRAGMA foreign_keys=ON` needed — FK constraint is decorative without it | Added to `init_db()` |
| Critical | Gemini | Race condition in `post_message` auto-create — check+create not atomic | Fixed: unconditionally call `create_room()` first (INSERT OR IGNORE is safe) |
| Warning | Architect+Backend+QA | `archive_room()` re-archives silently, overwrites timestamp | Fixed: added `AND status='live'` to WHERE clause |
| Warning | Architect | `ChatService.ping()` is dead code — server.py bypasses service | Removed `ChatService.ping()` |
| Warning | Backend | `list_rooms` no validation on status param | Added `VALID_ROOM_STATUSES` check |
| Warning | Gemini | DB parent directory may not exist on fresh install | Added `os.makedirs()` in `init_db()` |
| Warning | Gemini | Unbounded limit parameter — memory/context DoS | Added `max(1, min(limit, 1000))` clamp |
| Warning | Architect+QA | `post_message` return dict omits content | Added `content` to return dict |
| Suggestion | QA+Backend | `import pytest` inside function body in integration test | Fixed: moved to top-level |
| Suggestion | QA | Missing test for FK enforcement at db layer | Added `test_insert_message_fk_enforced` |
| Suggestion | QA | Missing test for double-archive behavior | Added `test_archive_room_already_archived` |
