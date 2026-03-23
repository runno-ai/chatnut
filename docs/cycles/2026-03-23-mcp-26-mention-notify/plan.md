# @Mention Notification Implementation Plan

## Context

When agents post `@security` in a chatroom, the mentioned agent only sees it if it happens to poll. If the agent has finished its work and stopped polling, the @mention is silently missed. This is a reliability gap observed during `/code-audit` runs where cross-consult pings went unanswered. MCP-26 adds an agent registry and @mention detection to `post_message`, returning mention data so the caller can `SendMessage` the targets.

## Goal

`post_message` automatically detects `@<name>` patterns, resolves them against a per-room agent registry, and returns matched agent task IDs in the response — enabling the caller to fire `SendMessage` notifications.

## Architecture

New `agent_registry` table stores `(room_id, agent_name, task_id)` per room. `register_agent` MCP tool lets the PM register each agent as they join. `post_message` parses `@<name>` patterns from content, resolves against the registry (case-insensitive via lowercase normalization), and includes `mentions: [{name, task_id}]` in the response. Unregistered mentions are silently skipped. chatnut provides the data; the calling agent (or skill) acts on it by SendMessaging the targets.

### Design Decisions

- **Return-mentions-to-caller**: chatnut is an MCP server — it can't call SendMessage itself. `post_message` returns mention data; the caller acts on it. Clean separation of concerns.
- **Case-insensitive matching**: `agent_name` is normalized to `strip().lower()` on both registration and lookup. Silent misses are the core problem — case sensitivity would undermine the feature.
- **Regex**: `(?<!\w)@([\w-]+)` — negative lookbehind for word characters. Correctly handles: `@name` at start, `text @name` after space, `(@name)` after punctuation. Correctly rejects: `user@example.com`, `Hello@name`.
- **`clear_room` does NOT clear registrations**: Agent registrations represent who is in the room (membership), not message history. Clearing messages should not reset the team roster.
- **`list_agents` on archived rooms is allowed**: Read-only operation on valid room data, consistent with `read_messages` on archived rooms.
- **`unregister_agent` is out of scope**: Stale registrations cause harmless no-ops (SendMessage to a dead task is ignored). Deferred to a future issue if needed.
- **Explicit `delete_agent_registrations()` in `delete_room()`**: Kept for consistency with existing `delete_read_cursors`/`delete_room_statuses` pattern, even though `ON DELETE CASCADE` handles it.
- **`post_message` response change is additive**: Adding `mentions: []` to every response is backward-compatible. Existing callers that destructure the response will ignore the extra key.

## Affected Areas

- Backend: `app/be/chatnut/` — db, service, mcp layers + migrations
- Tests: `app/be/tests/` — test_db, test_service, test_mcp, test_mcp_e2e

## Key Files

- `app/be/chatnut/migrations/004_agent_registry.sql` — New table DDL
- `app/be/chatnut/db.py` — CRUD functions for agent_registry
- `app/be/chatnut/service.py` — register_agent + mention detection in post_message
- `app/be/chatnut/mcp.py` — register_agent tool + list_agents tool
- `app/be/tests/test_service.py` — Primary test surface for mention logic

## Reusable Utilities

- `app/be/chatnut/db.py:upsert_room_status()` — Pattern to follow for UPSERT semantics
- `app/be/chatnut/db.py:delete_room_statuses()` — Pattern for CASCADE cleanup helper
- `app/be/chatnut/db.py:_now()` — Timestamp helper
- `app/be/chatnut/service.py:update_status()` — Pattern for validation + delegation

---

## Tasks

### Task 1: Migration — agent_registry table

**Files:**
- Create: `app/be/chatnut/migrations/004_agent_registry.sql`

**Step 1: Write migration SQL**

```sql
CREATE TABLE IF NOT EXISTS agent_registry (
    room_id TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    agent_name TEXT NOT NULL,
    task_id TEXT NOT NULL,
    registered_at TEXT NOT NULL,
    PRIMARY KEY (room_id, agent_name)
);
```

**Step 2: Verify migration applies**
```bash
cd app/be && uv run python -c "from chatnut.db import init_db; conn = init_db(':memory:'); print([r[0] for r in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()])"
```
Expected: output includes `agent_registry`

**Step 3: Commit**
```bash
git add app/be/chatnut/migrations/004_agent_registry.sql
git commit -m "feat: add agent_registry migration (MCP-26)"
```

---

### Task 2: DB layer — agent registry CRUD

**Files:**
- Modify: `app/be/chatnut/db.py`
- Test: `app/be/tests/test_db.py`

**Step 1: Write failing tests**

Add to `test_db.py`:

```python
def test_upsert_agent_registration(db):
    from chatnut.db import create_room, upsert_agent_registration, get_agent_registrations
    room = create_room(db, "proj", "dev")
    upsert_agent_registration(db, room.id, "security", "task-abc")
    regs = get_agent_registrations(db, room.id)
    assert len(regs) == 1
    assert regs[0]["agent_name"] == "security"
    assert regs[0]["task_id"] == "task-abc"


def test_upsert_agent_registration_updates_task_id(db):
    from chatnut.db import create_room, upsert_agent_registration, get_agent_registrations
    room = create_room(db, "proj", "dev")
    upsert_agent_registration(db, room.id, "security", "task-abc")
    upsert_agent_registration(db, room.id, "security", "task-xyz")
    regs = get_agent_registrations(db, room.id)
    assert len(regs) == 1
    assert regs[0]["task_id"] == "task-xyz"


def test_get_agent_registrations_empty(db):
    from chatnut.db import create_room, get_agent_registrations
    room = create_room(db, "proj", "dev")
    regs = get_agent_registrations(db, room.id)
    assert regs == []


def test_delete_agent_registrations(db):
    from chatnut.db import create_room, upsert_agent_registration, get_agent_registrations, delete_agent_registrations
    room = create_room(db, "proj", "dev")
    upsert_agent_registration(db, room.id, "security", "task-abc")
    upsert_agent_registration(db, room.id, "architect", "task-def")
    delete_agent_registrations(db, room.id)
    assert get_agent_registrations(db, room.id) == []


def test_agent_registrations_cascade_on_room_delete(db):
    """Verify ON DELETE CASCADE cleans up registrations when room is deleted directly."""
    from chatnut.db import create_room, upsert_agent_registration, archive_room
    room = create_room(db, "proj", "dev")
    upsert_agent_registration(db, room.id, "security", "task-abc")
    archive_room(db, "proj", "dev")
    # Delete room directly via SQL (bypass delete_room() which explicitly deletes)
    # to verify CASCADE works at the FK level
    with db:
        db.execute("DELETE FROM rooms WHERE id=?", (room.id,))
    row = db.execute("SELECT COUNT(*) FROM agent_registry WHERE room_id=?", (room.id,)).fetchone()
    assert row[0] == 0
```

**Step 2: Run tests — expect FAIL**
```bash
cd app/be && uv run pytest tests/test_db.py -xvs -k "agent_registration"
```
Expected: ImportError — functions don't exist yet

**Step 3: Implement in db.py**

Add three functions to `db.py`:

```python
def upsert_agent_registration(
    conn: sqlite3.Connection,
    room_id: str,
    agent_name: str,
    task_id: str,
) -> dict:
    """Register or update an agent's task_id in a room."""
    now = _now()
    with conn:
        conn.execute(
            """INSERT INTO agent_registry (room_id, agent_name, task_id, registered_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(room_id, agent_name) DO UPDATE
               SET task_id = excluded.task_id, registered_at = excluded.registered_at""",
            (room_id, agent_name, task_id, now),
        )
    return {"room_id": room_id, "agent_name": agent_name, "task_id": task_id, "registered_at": now}


def get_agent_registrations(conn: sqlite3.Connection, room_id: str) -> list[dict]:
    """Get all registered agents for a room."""
    rows = conn.execute(
        "SELECT room_id, agent_name, task_id, registered_at FROM agent_registry WHERE room_id = ? ORDER BY agent_name",
        (room_id,),
    ).fetchall()
    return [
        {"room_id": r[0], "agent_name": r[1], "task_id": r[2], "registered_at": r[3]}
        for r in rows
    ]


def delete_agent_registrations(conn: sqlite3.Connection, room_id: str) -> None:
    """Delete all agent registrations for a room. Explicit cleanup consistent with
    delete_read_cursors/delete_room_statuses pattern (CASCADE also handles this)."""
    with conn:
        conn.execute("DELETE FROM agent_registry WHERE room_id = ?", (room_id,))
```

Update `delete_room()` to call `delete_agent_registrations()`:

```python
def delete_room(conn: sqlite3.Connection, room_id: str) -> int:
    with conn:
        msg_cursor = conn.execute("DELETE FROM messages WHERE room_id=?", (room_id,))
        msg_count = msg_cursor.rowcount
        delete_read_cursors(conn, room_id)
        delete_room_statuses(conn, room_id)
        delete_agent_registrations(conn, room_id)
        conn.execute("DELETE FROM rooms WHERE id=?", (room_id,))
    return msg_count
```

**Step 4: Run tests — expect PASS**
```bash
cd app/be && uv run pytest tests/test_db.py -xvs -k "agent_registration"
```

**Step 5: Commit**
```bash
git add app/be/chatnut/db.py app/be/tests/test_db.py
git commit -m "feat: add agent_registry CRUD to db layer (MCP-26)"
```

---

### Task 3: Service layer — register_agent + mention detection

**Files:**
- Modify: `app/be/chatnut/service.py`
- Test: `app/be/tests/test_service.py`

**Step 1: Write failing tests**

Add to `test_service.py`:

```python
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
```

**Step 2: Run tests — expect FAIL**
```bash
cd app/be && uv run pytest tests/test_service.py -xvs -k "register_agent or mention or list_agents"
```
Expected: AttributeError — methods don't exist yet

**Step 3: Implement in service.py**

Add import at the top of service.py:

```python
import re
```

Add to the `from chatnut.db import (...)` block:

```python
    upsert_agent_registration,
    get_agent_registrations,
```

Add `_MENTION_RE` constant after `VALID_MESSAGE_TYPES`:

```python
_MENTION_RE = re.compile(r'(?<!\w)@([\w-]+)')
```

Add methods to ChatService:

```python
def register_agent(self, room_id: str, agent_name: str, task_id: str) -> dict:
    """Register an agent's task_id in a room for @mention notifications.

    agent_name is normalized to lowercase (strip + lower) for case-insensitive matching.

    Raises ValueError if the room does not exist or is archived,
    or if agent_name/task_id are empty.
    """
    if not agent_name or not agent_name.strip():
        raise ValueError("agent_name must be a non-empty string")
    if not task_id or not task_id.strip():
        raise ValueError("task_id must be a non-empty string")
    room_obj = get_room_by_id(self.db, room_id)
    if room_obj is None:
        raise ValueError(f"Room '{room_id}' not found")
    if room_obj.status == "archived":
        raise ValueError(f"Room '{room_obj.name}' is archived — cannot register agents")
    return upsert_agent_registration(self.db, room_id, agent_name.strip().lower(), task_id.strip())

def list_agents(self, room_id: str) -> dict:
    """List all registered agents in a room.

    Read-only — works on both live and archived rooms.
    Raises ValueError if the room does not exist.
    """
    room_obj = get_room_by_id(self.db, room_id)
    if room_obj is None:
        raise ValueError(f"Room '{room_id}' not found")
    return {"agents": get_agent_registrations(self.db, room_id)}

def _detect_mentions(self, room_id: str, content: str) -> list[dict]:
    """Parse @mentions from content and resolve against agent registry.

    Names are lowercased before lookup for case-insensitive matching.
    Returns list of {name, task_id} for registered agents only.
    Unregistered @mentions are silently skipped.
    """
    names = set(n.lower() for n in _MENTION_RE.findall(content))
    if not names:
        return []
    registrations = get_agent_registrations(self.db, room_id)
    registry = {r["agent_name"]: r["task_id"] for r in registrations}
    return [{"name": name, "task_id": registry[name]} for name in sorted(names) if name in registry]
```

Update `post_message_by_room_id` to include mentions:

```python
def post_message_by_room_id(self, room_id, sender, content, message_type="message"):
    if message_type not in VALID_MESSAGE_TYPES:
        raise ValueError(f"Invalid message_type '{message_type}' — must be one of {VALID_MESSAGE_TYPES}")
    room_obj = get_room_by_id(self.db, room_id)
    if room_obj is None:
        raise ValueError(f"Room '{room_id}' not found")
    if room_obj.status == "archived":
        raise ValueError(f"Room '{room_obj.name}' is archived — cannot post messages")
    msg = insert_message(self.db, room_id, sender, content, message_type=message_type)
    result = msg.to_dict()
    result["mentions"] = self._detect_mentions(room_id, content)
    return result
```

Update `post_message` (by project/room name) similarly:

```python
def post_message(self, project, room, sender, content, message_type="message"):
    if message_type not in VALID_MESSAGE_TYPES:
        raise ValueError(f"Invalid message_type '{message_type}' — must be one of {VALID_MESSAGE_TYPES}")
    room_obj = get_room(self.db, project=project, name=room)
    if room_obj is None:
        raise ValueError(f"Room '{room}' in project '{project}' not found — use init_room() to create it first")
    if room_obj.status == "archived":
        raise ValueError(f"Room '{room}' in project '{project}' is archived — cannot post messages")
    msg = insert_message(self.db, room_obj.id, sender, content, message_type=message_type)
    result = msg.to_dict()
    result["mentions"] = self._detect_mentions(room_obj.id, content)
    return result
```

**Step 4: Run tests — expect PASS**
```bash
cd app/be && uv run pytest tests/test_service.py -xvs -k "register_agent or mention or list_agents"
```

**Step 5: Commit**
```bash
git add app/be/chatnut/service.py app/be/tests/test_service.py
git commit -m "feat: add register_agent + @mention detection in post_message (MCP-26)"
```

---

### Task 4: MCP tool layer — register_agent + list_agents tools

**Files:**
- Modify: `app/be/chatnut/mcp.py`
- Modify: `app/be/tests/test_mcp.py`

**Step 1: Write failing tests**

Add to `test_mcp.py`, following the existing factory-injection pattern from `test_ping_uses_live_service_path`:

```python
def test_register_agent_tool(db):
    from chatnut import mcp as mcp_module
    from chatnut.service import ChatService

    svc = ChatService(db)
    original_factory = mcp_module._service_factory
    mcp_module.set_service_factory(lambda: svc)
    try:
        room = svc.init_room("proj", "dev")
        result = mcp_module.register_agent(room["id"], "security", "task-abc")
        assert result["agent_name"] == "security"
        assert result["task_id"] == "task-abc"
    finally:
        mcp_module.set_service_factory(original_factory)


def test_list_agents_tool(db):
    from chatnut import mcp as mcp_module
    from chatnut.service import ChatService

    svc = ChatService(db)
    original_factory = mcp_module._service_factory
    mcp_module.set_service_factory(lambda: svc)
    try:
        room = svc.init_room("proj", "dev")
        mcp_module.register_agent(room["id"], "security", "task-abc")
        mcp_module.register_agent(room["id"], "architect", "task-def")
        result = mcp_module.list_agents(room["id"])
        assert len(result["agents"]) == 2
    finally:
        mcp_module.set_service_factory(original_factory)


def test_post_message_returns_mentions(db):
    from chatnut import mcp as mcp_module
    from chatnut.service import ChatService

    svc = ChatService(db)
    original_factory = mcp_module._service_factory
    mcp_module.set_service_factory(lambda: svc)
    try:
        room = svc.init_room("proj", "dev")
        mcp_module.register_agent(room["id"], "security", "task-abc")
        result = mcp_module.post_message(room["id"], "pm", "@security check this")
        assert result["mentions"] == [{"name": "security", "task_id": "task-abc"}]
    finally:
        mcp_module.set_service_factory(original_factory)
```

Update `test_all_tools_registered` expected set:

```python
    expected = {
        "ping", "init_room", "post_message", "read_messages",
        "list_rooms", "archive_room", "delete_room", "clear_room",
        "search", "list_projects", "mark_read", "wait_for_messages",
        "update_status", "get_team_status",
        "register_agent", "list_agents",
    }
```

**Step 2: Run tests — expect FAIL**
```bash
cd app/be && uv run pytest tests/test_mcp.py -xvs -k "register_agent or list_agents or returns_mentions or all_tools"
```
Expected: ImportError — tools don't exist yet

**Step 3: Implement in mcp.py**

Add two new MCP tools:

```python
@mcp.tool()
def register_agent(room_id: str, agent_name: str, task_id: str) -> dict:
    """Register an agent in a room for @mention notifications.

    When a message containing @<agent_name> is posted to this room,
    post_message will include the agent's task_id in its response,
    enabling the caller to SendMessage the mentioned agent.

    UPSERT semantics — re-registering updates the task_id.
    agent_name is normalized to lowercase for case-insensitive matching.

    Args:
        room_id: The room UUID returned by init_room.
        agent_name: The agent's role name used in @mentions (e.g., "security", "architect").
        task_id: The CC agent/task name to SendMessage to when @mentioned.

    Raises:
        ValueError: If the room does not exist or is archived.
    """
    return _get_service().register_agent(room_id, agent_name, task_id)


@mcp.tool()
def list_agents(room_id: str) -> dict:
    """List all registered agents in a room.

    Args:
        room_id: The room UUID returned by init_room.

    Returns:
        {"agents": [{room_id, agent_name, task_id, registered_at}, ...]}

    Raises:
        ValueError: If the room does not exist.
    """
    return _get_service().list_agents(room_id)
```

**Step 4: Run tests — expect PASS**
```bash
cd app/be && uv run pytest tests/test_mcp.py -xvs -k "register_agent or list_agents or returns_mentions or all_tools"
```

**Step 5: Commit**
```bash
git add app/be/chatnut/mcp.py app/be/tests/test_mcp.py
git commit -m "feat: add register_agent + list_agents MCP tools (MCP-26)"
```

---

### Task 5: E2E MCP test — full flow

**Files:**
- Modify: `app/be/tests/test_mcp_e2e.py`

**Step 1: Write E2E test**

Using the existing `mcp_svc` fixture and `call()` helper pattern:

```python
@pytest.mark.anyio
async def test_e2e_mention_notification_flow(mcp_svc):
    """Full flow: init room -> register agents -> post with @mention -> verify mentions returned."""
    async with Client(mcp_module.mcp) as client:
        # Create room
        room = await call(client, "init_room", {"project": "test", "name": "mention-test"})

        # Register agents
        reg1 = await call(client, "register_agent", {
            "room_id": room["id"], "agent_name": "security", "task_id": "task-sec"
        })
        assert reg1["agent_name"] == "security"

        await call(client, "register_agent", {
            "room_id": room["id"], "agent_name": "architect", "task_id": "task-arch"
        })

        # Post with mentions
        msg = await call(client, "post_message", {
            "room_id": room["id"],
            "sender": "pm",
            "content": "@security @architect please cross-review"
        })
        assert len(msg["mentions"]) == 2
        names = {m["name"] for m in msg["mentions"]}
        assert names == {"security", "architect"}

        # Post with unregistered mention — silently skipped
        msg2 = await call(client, "post_message", {
            "room_id": room["id"],
            "sender": "pm",
            "content": "@unknown check this"
        })
        assert msg2["mentions"] == []

        # List agents
        agents = await call(client, "list_agents", {"room_id": room["id"]})
        assert len(agents["agents"]) == 2


@pytest.mark.anyio
async def test_e2e_register_agent_error_paths(mcp_svc):
    """Verify error propagation through MCP layer for register_agent."""
    async with Client(mcp_module.mcp, raise_on_error=False) as client:
        # Non-existent room
        result = await client.call_tool("register_agent", {
            "room_id": "nonexistent", "agent_name": "security", "task_id": "task-abc"
        })
        assert result.is_error

        # Create and archive room, then try to register
        room = await call(client, "init_room", {"project": "test", "name": "err-test"})
        await call(client, "archive_room", {"project": "test", "name": "err-test"})
        result2 = await client.call_tool("register_agent", {
            "room_id": room["id"], "agent_name": "security", "task_id": "task-abc"
        })
        assert result2.is_error
```

**Step 2: Run test — expect PASS** (all implementation done in prior tasks)
```bash
cd app/be && uv run pytest tests/test_mcp_e2e.py -xvs -k "mention"
```

**Step 3: Commit**
```bash
git add app/be/tests/test_mcp_e2e.py
git commit -m "test: add E2E tests for @mention notification flow (MCP-26)"
```

---

### Task 6: Documentation Update

- [ ] Update CLAUDE.md Tools table — add `register_agent` and `list_agents`, update `post_message` description
- [ ] Update CLAUDE.md Schema section — add `agent_registry` table DDL
- [ ] Update CLAUDE.md Design Decisions — add mention notification design decision
- [ ] Update SKILL.md — add agent registration setup and @mention behavior to usage docs

---

## Verification

```bash
cd app/be && uv run pytest -xvs
```

Expected: All existing + new tests pass. No regressions.

```bash
cd app/be && uv run pytest tests/test_mcp_e2e.py -xvs
```

Expected: E2E mention notification flow passes end-to-end.

## AI Review Findings

| Severity | Source | Finding | Action |
|----------|--------|---------|--------|
| Warning | All 4 reviewers | MCP test fixture: use factory-injection, not nonexistent `service` fixture | Fixed in Task 4 |
| Warning | Architect, Backend-dev, Codex, MiniMax | `test_all_tools_registered` needs `register_agent` + `list_agents` | Fixed in Task 4 |
| Warning | MiniMax | Regex `(?:^\|(?<=\s))` false-positive on `Hello@name` — use `(?<!\w)` lookbehind | Fixed in Task 3 |
| Warning | Codex, MiniMax | No name canonicalization — `strip().lower()` needed | Fixed in Task 3 |
| Warning | Backend-dev | Missing tests: email negative case, newline mention | Added in Task 3 |
| Warning | MiniMax | Missing test: `Hello@name` false positive | Added in Task 3 |
| Warning | Codex | Missing test: punctuation-adjacent `(@security)` | Added in Task 3 |
| Suggestion | Architect | CASCADE test should verify FK path, not explicit delete | Fixed in Task 2 |
| Suggestion | Architect | E2E should test error paths | Added in Task 5 |
| Suggestion | MiniMax | `list_agents` on archived room: document as intentional | Added test in Task 3, documented in Architecture |
| Suggestion | Architect, MiniMax | `unregister_agent` out of scope | Documented in Architecture |
| Suggestion | Architect | `clear_room` should/shouldn't clear registrations | Documented: NO — registrations are membership, not messages |
