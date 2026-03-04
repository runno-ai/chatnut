# Room Discovery + Team Status Implementation Plan

## Context

Spawned team agents fail with "room ID doesn't exist" because chatroom UUIDs are passed via template placeholders that often don't get substituted. Additionally, the PM has no way to see what teammates are doing without waiting for DMs. This plan adds disk-based room ID discovery, a decoupled team status system, and a sticky StatusBar UI.

## Goal

Reliable room ID discovery via `~/.claude/teams/{team_name}/chatroom.json`, a `room_status` table with MCP tools and SSE for real-time team presence, and a `<StatusBar>` component in the web UI.

## Architecture

Three independent features that compose naturally: (1) `init_room` gains an optional `team_name` param and writes room metadata to the team's config directory on disk, (2) a new `room_status` table (UPSERT semantics) with `update_status`/`get_team_status` MCP tools and polling-based SSE endpoint, (3) a React `StatusBar` component powered by a `useStatus` hook consuming the new SSE stream.

## Affected Areas

- Backend: `db.py`, `service.py`, `mcp.py`, `routes.py`
- Frontend: new `StatusBar.tsx`, new `useStatus.ts`, `ChatView.tsx`, `types.ts`
- Config: `SKILL.md`, `CLAUDE.md`

## Key Files

- `app/be/chatnut/service.py` — Core business logic: new status methods
- `app/be/chatnut/mcp.py` — MCP tool definitions + init_room disk write
- `app/be/chatnut/routes.py` — REST + SSE endpoints for status (polling-based, consistent with existing SSE)
- `app/fe/src/components/ChatView.tsx` — StatusBar integration point
- `SKILL.md` — Agent-facing tool docs + teammate instructions

## Reusable Utilities

- `app/be/chatnut/routes.py:chatroom_event_generator()` — SSE polling + hash-based change detection pattern to follow for status stream
- `app/be/chatnut/db.py:init_db()` — migration system auto-applies numbered `.sql` files
- `app/fe/src/hooks/useSSE.ts` — EventSource + reconnect pattern with `useRef` to follow for `useStatus`
- `app/fe/src/components/Message.tsx:formatTimestamp()` — extract to shared utility for reuse

---

## Tasks

### Task 1: DB Migration — room_status table

**Files:**
- Create: `app/be/migrations/003_room_status.sql`
- Modify: `app/be/chatnut/db.py`
- Test: `app/be/tests/test_db.py`

**Step 1: Write the failing test**

```python
# In test_db.py — add to existing test file
def test_room_status_table_exists(db):
    """Verify room_status table is created by migrations."""
    cursor = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='room_status'"
    )
    assert cursor.fetchone() is not None

def test_room_status_upsert(db):
    """Verify UPSERT semantics on room_status."""
    from chatnut.db import create_room, upsert_room_status, get_room_statuses
    room = create_room(db, "test-project", "test-room")
    room_id = room["id"]

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
    from chatnut.db import create_room, upsert_room_status, get_room_statuses, delete_room
    room = create_room(db, "test-project", "test-room")
    room_id = room["id"]
    upsert_room_status(db, room_id, "reviewer-1", "Working")

    # Archive then delete via db function (not raw SQL)
    db.execute("UPDATE rooms SET status='archived', archived_at=datetime('now') WHERE id=?", (room_id,))
    db.commit()
    delete_room(db, room_id)

    statuses = get_room_statuses(db, room_id)
    assert len(statuses) == 0

def test_room_status_length_constraint(db):
    """Verify status text length is capped at 500 chars."""
    import sqlite3
    from chatnut.db import create_room, upsert_room_status
    room = create_room(db, "test-project", "test-room")
    room_id = room["id"]

    # 500 chars should succeed
    upsert_room_status(db, room_id, "agent", "x" * 500)

    # 501 chars should fail
    import pytest
    with pytest.raises(sqlite3.IntegrityError):
        upsert_room_status(db, room_id, "agent", "x" * 501)
```

**Step 2: Run test — expect FAIL**
```bash
cd app/be && uv run pytest tests/test_db.py::test_room_status_table_exists tests/test_db.py::test_room_status_upsert tests/test_db.py::test_room_status_cascade_delete tests/test_db.py::test_room_status_length_constraint -xvs
```

**Step 3: Implement minimal code**

Create `app/be/migrations/003_room_status.sql`:
```sql
CREATE TABLE IF NOT EXISTS room_status (
    room_id TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    sender TEXT NOT NULL,
    status TEXT NOT NULL CHECK(length(status) <= 500),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (room_id, sender)
);
```

Add to `app/be/chatnut/db.py`:
```python
def upsert_room_status(
    conn: sqlite3.Connection,
    room_id: str,
    sender: str,
    status: str,
) -> dict:
    """Upsert a sender's status in a room. Returns the status record."""
    now = datetime.now(timezone.utc).isoformat()
    with conn:
        conn.execute(
            """
            INSERT INTO room_status (room_id, sender, status, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(room_id, sender) DO UPDATE
            SET status = excluded.status, updated_at = excluded.updated_at
            """,
            (room_id, sender, status, now),
        )
    return {"room_id": room_id, "sender": sender, "status": status, "updated_at": now}


def get_room_statuses(conn: sqlite3.Connection, room_id: str) -> list[dict]:
    """Get all current statuses for a room."""
    rows = conn.execute(
        "SELECT room_id, sender, status, updated_at FROM room_status WHERE room_id = ? ORDER BY updated_at DESC",
        (room_id,),
    ).fetchall()
    return [
        {"room_id": r[0], "sender": r[1], "status": r[2], "updated_at": r[3]}
        for r in rows
    ]


def delete_room_statuses(conn: sqlite3.Connection, room_id: str) -> None:
    """Delete all statuses for a room."""
    conn.execute("DELETE FROM room_status WHERE room_id = ?", (room_id,))
```

Also add `delete_room_statuses(conn, room_id)` call inside `db.delete_room()`, before `DELETE FROM rooms`:
```python
# In delete_room(), add after delete_read_cursors and before DELETE FROM rooms:
delete_room_statuses(conn, room_id)
```

**Step 4: Run test — expect PASS**
```bash
cd app/be && uv run pytest tests/test_db.py::test_room_status_table_exists tests/test_db.py::test_room_status_upsert tests/test_db.py::test_room_status_cascade_delete tests/test_db.py::test_room_status_length_constraint -xvs
```

**Step 5: Commit**
```bash
git add app/be/migrations/003_room_status.sql app/be/chatnut/db.py app/be/tests/test_db.py
git commit -m "feat: add room_status table with UPSERT semantics and length constraint"
```

---

### Task 2: Service Layer — update_status and get_team_status

**Files:**
- Modify: `app/be/chatnut/service.py`
- Test: `app/be/tests/test_service.py`

**Step 1: Write the failing test**

```python
# In test_service.py
def test_update_status(service):
    room = service.init_room("test-project", "test-room")
    result = service.update_status(room["id"], "reviewer-1", "Reviewing auth module")
    assert result["sender"] == "reviewer-1"
    assert result["status"] == "Reviewing auth module"
    assert "updated_at" in result

def test_update_status_upsert(service):
    room = service.init_room("test-project", "test-room")
    service.update_status(room["id"], "reviewer-1", "Starting")
    result = service.update_status(room["id"], "reviewer-1", "Completed")
    assert result["status"] == "Completed"

def test_update_status_nonexistent_room(service):
    import pytest
    with pytest.raises(ValueError, match="not found"):
        service.update_status("nonexistent-uuid", "reviewer-1", "Working")

def test_update_status_archived_room(service):
    import pytest
    room = service.init_room("test-project", "test-room")
    service.archive_room("test-project", "test-room")
    with pytest.raises(ValueError, match="archived"):
        service.update_status(room["id"], "reviewer-1", "Working")

def test_get_team_status(service):
    room = service.init_room("test-project", "test-room")
    service.update_status(room["id"], "reviewer-1", "Reviewing auth")
    service.update_status(room["id"], "codex", "Running analysis")
    result = service.get_team_status(room["id"])
    assert len(result["statuses"]) == 2
    senders = {s["sender"] for s in result["statuses"]}
    assert senders == {"reviewer-1", "codex"}

def test_get_team_status_empty(service):
    room = service.init_room("test-project", "test-room")
    result = service.get_team_status(room["id"])
    assert result["statuses"] == []

def test_get_team_status_nonexistent_room(service):
    import pytest
    with pytest.raises(ValueError, match="not found"):
        service.get_team_status("nonexistent-uuid")
```

**Step 2: Run test — expect FAIL**
```bash
cd app/be && uv run pytest tests/test_service.py -k "test_update_status or test_get_team_status" -xvs
```

**Step 3: Implement minimal code**

Add to `service.py` (note: `self.db`, not `self._conn`):
```python
def update_status(self, room_id: str, sender: str, status: str) -> dict:
    """Update a sender's status in a room. UPSERT semantics."""
    room = db.get_room_by_id(self.db, room_id)
    if not room:
        raise ValueError(f"Room {room_id!r} not found")
    if room["status"] == "archived":
        raise ValueError(f"Room {room_id!r} is archived")
    return db.upsert_room_status(self.db, room_id, sender, status)

def get_team_status(self, room_id: str) -> dict:
    """Get all current statuses for a room."""
    room = db.get_room_by_id(self.db, room_id)
    if not room:
        raise ValueError(f"Room {room_id!r} not found")
    statuses = db.get_room_statuses(self.db, room_id)
    return {"room_id": room_id, "statuses": statuses}
```

**Step 4: Run test — expect PASS**
```bash
cd app/be && uv run pytest tests/test_service.py -k "test_update_status or test_get_team_status" -xvs
```

**Step 5: Commit**
```bash
git add app/be/chatnut/service.py app/be/tests/test_service.py
git commit -m "feat: add update_status and get_team_status to ChatService"
```

---

### Task 3: MCP Tools — update_status and get_team_status

**Files:**
- Modify: `app/be/chatnut/mcp.py`
- Test: `app/be/tests/test_mcp.py`

Tests use the existing direct-call pattern (not `client` fixture):

**Step 1: Write the failing test**

```python
# In test_mcp.py — uses existing direct-call pattern
import chatnut.mcp as mcp_module

def test_update_status(db, monkeypatch):
    monkeypatch.setenv("CHATNUT_OPEN_BROWSER", "0")
    mcp_module.set_service_factory(lambda: ChatService(db))
    room = mcp_module.init_room(project="test", name="status-room")
    result = mcp_module.update_status(room_id=room["id"], sender="reviewer-1", status="Reviewing auth")
    assert result["sender"] == "reviewer-1"
    assert result["status"] == "Reviewing auth"

def test_get_team_status(db, monkeypatch):
    monkeypatch.setenv("CHATNUT_OPEN_BROWSER", "0")
    mcp_module.set_service_factory(lambda: ChatService(db))
    room = mcp_module.init_room(project="test", name="status-room2")
    mcp_module.update_status(room_id=room["id"], sender="reviewer-1", status="Working")
    mcp_module.update_status(room_id=room["id"], sender="codex", status="Analyzing")
    result = mcp_module.get_team_status(room_id=room["id"])
    assert len(result["statuses"]) == 2
```

**Step 2: Run test — expect FAIL**
```bash
cd app/be && uv run pytest tests/test_mcp.py::test_update_status tests/test_mcp.py::test_get_team_status -xvs
```

**Step 3: Implement minimal code**

Add to `mcp.py`:

```python
@mcp.tool()
def update_status(room_id: str, sender: str, status: str) -> dict:
    """Update a sender's current status in a room. UPSERT — only the latest status per sender is kept.

    Use this for team presence/activity tracking. Status is freeform text
    (e.g., "Reviewing auth module", "Blocked on test fixtures", "Completed analysis").

    Args:
        room_id: The room UUID.
        sender: Name or identifier of the agent.
        status: Current activity description (freeform text, max 500 chars).
    """
    svc = _get_service()
    return svc.update_status(room_id, sender, status)

@mcp.tool()
def get_team_status(room_id: str) -> dict:
    """Get the current status of all team members in a room.

    Returns the latest status per sender — a team dashboard snapshot.

    Args:
        room_id: The room UUID.
    """
    svc = _get_service()
    return svc.get_team_status(room_id)
```

**Step 4: Run test — expect PASS**
```bash
cd app/be && uv run pytest tests/test_mcp.py::test_update_status tests/test_mcp.py::test_get_team_status -xvs
```

**Step 5: Commit**
```bash
git add app/be/chatnut/mcp.py app/be/tests/test_mcp.py
git commit -m "feat: add update_status and get_team_status MCP tools"
```

---

### Task 4: init_room Enhancement — team_name param + disk write

**Files:**
- Modify: `app/be/chatnut/mcp.py`
- Test: `app/be/tests/test_mcp.py`

**Step 1: Write the failing test**

```python
# In test_mcp.py — direct-call pattern
import json, os

def test_init_room_writes_team_config(db, tmp_path, monkeypatch):
    """init_room with team_name writes chatroom.json to team config dir."""
    monkeypatch.setenv("CHATNUT_OPEN_BROWSER", "0")
    monkeypatch.setenv("CLAUDE_TEAMS_DIR", str(tmp_path / "teams"))
    mcp_module.set_service_factory(lambda: ChatService(db))

    # Create the team directory (simulates TeamCreate)
    team_dir = tmp_path / "teams" / "my-team"
    team_dir.mkdir(parents=True)

    room = mcp_module.init_room(project="test", name="team-room", team_name="my-team")

    chatroom_file = team_dir / "chatroom.json"
    assert chatroom_file.exists()
    data = json.loads(chatroom_file.read_text())
    assert data["room_id"] == room["id"]
    assert data["project"] == "test"
    assert data["name"] == "team-room"

def test_init_room_without_team_name_no_file(db, tmp_path, monkeypatch):
    """init_room without team_name does not write any file."""
    monkeypatch.setenv("CHATNUT_OPEN_BROWSER", "0")
    monkeypatch.setenv("CLAUDE_TEAMS_DIR", str(tmp_path / "teams"))
    mcp_module.set_service_factory(lambda: ChatService(db))

    teams_dir = tmp_path / "teams"
    teams_dir.mkdir()

    mcp_module.init_room(project="test", name="no-team-room")
    # No team directories should have been created
    assert list(teams_dir.iterdir()) == []

def test_init_room_team_write_failure_nonfatal(db, tmp_path, monkeypatch):
    """init_room still succeeds if team_name disk write fails."""
    monkeypatch.setenv("CHATNUT_OPEN_BROWSER", "0")
    monkeypatch.setenv("CLAUDE_TEAMS_DIR", "/nonexistent/path")
    mcp_module.set_service_factory(lambda: ChatService(db))

    # Should not raise — disk write failure is non-fatal
    room = mcp_module.init_room(project="test", name="fail-room", team_name="no-team")
    assert room["id"]  # Room was created successfully

def test_init_room_rejects_path_traversal(db, tmp_path, monkeypatch):
    """init_room with path traversal in team_name does not write any file."""
    monkeypatch.setenv("CHATNUT_OPEN_BROWSER", "0")
    monkeypatch.setenv("CLAUDE_TEAMS_DIR", str(tmp_path / "teams"))
    mcp_module.set_service_factory(lambda: ChatService(db))

    teams_dir = tmp_path / "teams"
    teams_dir.mkdir()

    # Path traversal attempts should be silently rejected
    room = mcp_module.init_room(project="test", name="traversal-room", team_name="../../etc")
    assert room["id"]  # Room created successfully
    # No files written outside teams dir
    assert not (tmp_path / "etc").exists()
    assert list(teams_dir.iterdir()) == []
```

**Step 2: Run test — expect FAIL**
```bash
cd app/be && uv run pytest tests/test_mcp.py -k "test_init_room_writes_team_config or test_init_room_without_team_name or test_init_room_team_write_failure" -xvs
```

**Step 3: Implement minimal code**

Modify `init_room` in `mcp.py` — add `team_name` parameter and `_write_team_chatroom` helper:
```python
@mcp.tool()
def init_room(
    project: str,
    name: str,
    branch: str | None = None,
    description: str | None = None,
    team_name: str | None = None,
) -> dict:
    """Create a new chatroom. Idempotent — returns existing room if already created.

    Args:
        project: Project name for scoping.
        name: Chatroom name (unique within project).
        branch: Optional git branch.
        description: Optional room description.
        team_name: Optional team name. When provided, writes room metadata
                   to team config dir for agent discovery.
    """
    svc = _get_service()
    result = svc.init_room(project, name, branch, description)
    # ... existing web_url + browser logic preserved ...

    if team_name:
        _write_team_chatroom(team_name, result)

    return result


def _write_team_chatroom(team_name: str, room_data: dict) -> None:
    """Write room metadata to team config dir. Non-fatal on failure."""
    import json as _json, logging
    # Sanitize team_name to prevent path traversal (e.g., "../../etc")
    safe_name = os.path.basename(team_name)
    if not safe_name or safe_name != team_name:
        logging.getLogger(__name__).warning("Rejected team_name %r (sanitized to %r)", team_name, safe_name)
        return
    teams_dir = os.environ.get("CLAUDE_TEAMS_DIR", os.path.expanduser("~/.claude/teams"))
    team_dir = os.path.join(teams_dir, safe_name)
    if not os.path.isdir(team_dir):
        return
    chatroom_file = os.path.join(team_dir, "chatroom.json")
    payload = {"room_id": room_data["id"], "project": room_data["project"], "name": room_data["name"]}
    if "web_url" in room_data:
        payload["web_url"] = room_data["web_url"]
    try:
        with open(chatroom_file, "w") as f:
            _json.dump(payload, f, indent=2)
    except OSError:
        logging.getLogger(__name__).warning("Failed to write %s", chatroom_file, exc_info=True)
```

**Step 4: Run test — expect PASS**
```bash
cd app/be && uv run pytest tests/test_mcp.py -k "test_init_room_writes_team_config or test_init_room_without_team_name or test_init_room_team_write_failure" -xvs
```

**Step 5: Commit**
```bash
git add app/be/chatnut/mcp.py app/be/tests/test_mcp.py
git commit -m "feat: init_room writes chatroom.json to team config dir"
```

---

### Task 5: REST + SSE Endpoints for Status

**Files:**
- Modify: `app/be/chatnut/routes.py`
- Test: `app/be/tests/test_routes.py`

SSE uses **polling + hash-based change detection** (consistent with existing `chatroom_event_generator`), NOT queue-based waiters. This keeps the routes → service layering clean (no import from mcp.py).

**Step 1: Write the failing test**

```python
# In test_routes.py
def test_get_room_status(test_client, service):
    room = service.init_room("test-project", "status-room")
    service.update_status(room["id"], "reviewer-1", "Working")
    service.update_status(room["id"], "codex", "Analyzing")

    resp = test_client.get(f"/api/chatrooms/{room['id']}/status")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["statuses"]) == 2

def test_get_room_status_nonexistent(test_client):
    resp = test_client.get("/api/chatrooms/nonexistent/status")
    assert resp.status_code == 404
```

**Step 2: Run test — expect FAIL**
```bash
cd app/be && uv run pytest tests/test_routes.py::test_get_room_status tests/test_routes.py::test_get_room_status_nonexistent -xvs
```

**Step 3: Implement minimal code**

Add inside `create_router()` in `routes.py` (using closure `get_service` pattern):

```python
@router.get("/chatrooms/{room_id}/status")
async def get_room_status(room_id: str):
    svc = get_service()
    try:
        result = await anyio.to_thread.run_sync(lambda: svc.get_team_status(room_id))
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Room {room_id!r} not found")
    return result


async def status_event_generator(svc, room_id, is_disconnected=None):
    """SSE generator for room status changes. Polling-based with hash change detection."""
    import hashlib
    last_hash = ""
    keepalive_counter = 0
    while True:
        if is_disconnected and await is_disconnected():
            break
        statuses = await anyio.to_thread.run_sync(lambda: svc.get_team_status(room_id))
        payload = json.dumps(statuses, sort_keys=True)
        h = hashlib.sha256(payload.encode()).hexdigest()
        if h != last_hash:
            last_hash = h
            keepalive_counter = 0
            yield {"data": payload}
        else:
            keepalive_counter += 1
            if keepalive_counter >= 30:  # 15s keepalive at 0.5s poll
                keepalive_counter = 0
                yield {"comment": "keepalive"}
        await anyio.sleep(POLL_INTERVAL)


@router.get("/stream/status")
async def stream_status(request: Request, room_id: str):
    svc = get_service()
    if not await anyio.to_thread.run_sync(lambda: svc.room_exists(room_id)):
        raise HTTPException(status_code=404, detail=f"Room {room_id!r} not found")
    return EventSourceResponse(
        status_event_generator(svc, room_id, is_disconnected=request.is_disconnected)
    )
```

**Step 4: Run test — expect PASS**
```bash
cd app/be && uv run pytest tests/test_routes.py::test_get_room_status tests/test_routes.py::test_get_room_status_nonexistent -xvs
```

**Step 5: Commit**
```bash
git add app/be/chatnut/routes.py app/be/tests/test_routes.py
git commit -m "feat: add REST + SSE endpoints for room status"
```

---

### Task 6: Frontend — StatusBar Component + useStatus Hook

**Files:**
- Create: `app/fe/src/hooks/useStatus.ts`
- Create: `app/fe/src/components/StatusBar.tsx`
- Create: `app/fe/src/utils/timeAgo.ts`
- Modify: `app/fe/src/types.ts`
- Modify: `app/fe/src/components/ChatView.tsx`

**Step 1: Add TypeScript interfaces**

Add to `types.ts`:
```typescript
export interface RoomStatus {
  sender: string;
  status: string;
  updated_at: string;
}

export interface TeamStatusResponse {
  room_id: string;
  statuses: RoomStatus[];
}
```

**Step 2: Extract shared timeAgo utility**

Create `app/fe/src/utils/timeAgo.ts`:
```typescript
export function timeAgo(dateStr: string): string {
  const seconds = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000);
  if (seconds < 60) return "now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return new Date(dateStr).toLocaleDateString();
}
```

**Step 3: Create useStatus hook**

Create `app/fe/src/hooks/useStatus.ts` — follows `useSSE.ts` ref-based pattern:
```typescript
import { useState, useEffect, useRef } from "react";
import type { RoomStatus } from "@/types";

export function useStatus(roomId: string | null): RoomStatus[] {
  const [statuses, setStatuses] = useState<RoomStatus[]>([]);
  const esRef = useRef<EventSource | null>(null);
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const closedRef = useRef(false);

  useEffect(() => {
    if (!roomId) {
      setStatuses([]);
      return;
    }

    closedRef.current = false;

    function connect() {
      if (closedRef.current) return;

      const es = new EventSource(`/api/stream/status?room_id=${roomId}`);
      esRef.current = es;

      es.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          setStatuses(data.statuses ?? []);
        } catch { /* ignore parse errors */ }
      };

      es.onerror = () => {
        es.close();
        if (!closedRef.current) {
          retryRef.current = setTimeout(connect, 3000);
        }
      };
    }

    connect();

    return () => {
      closedRef.current = true;
      if (retryRef.current) clearTimeout(retryRef.current);
      if (esRef.current) esRef.current.close();
    };
  }, [roomId]);

  return statuses;
}
```

**Step 4: Create StatusBar component**

Create `app/fe/src/components/StatusBar.tsx`:
```tsx
import { timeAgo } from "@/utils/timeAgo";
import type { RoomStatus } from "@/types";

function statusColor(status: string, updatedAt: string): string {
  const seconds = (Date.now() - new Date(updatedAt).getTime()) / 1000;
  if (/block/i.test(status)) return "text-yellow-500";
  if (seconds > 300) return "text-gray-500";
  return "text-green-400";
}

function dotColor(status: string, updatedAt: string): string {
  if (/block/i.test(status)) return "bg-yellow-500";
  const seconds = (Date.now() - new Date(updatedAt).getTime()) / 1000;
  if (seconds > 300) return "bg-gray-500";
  return "bg-green-400";
}

export function StatusBar({ statuses }: { statuses: RoomStatus[] }) {
  if (statuses.length === 0) return null;

  return (
    <div className="px-4 py-2 border-b border-gray-800 bg-gray-900/30 flex flex-wrap gap-x-4 gap-y-1 text-xs">
      {statuses.map((s) => (
        <span key={s.sender} className="flex items-center gap-1.5 shrink-0">
          <span className={`inline-block w-1.5 h-1.5 rounded-full ${dotColor(s.status, s.updated_at)}`} />
          <span className="text-gray-300 font-medium">{s.sender}</span>
          <span className={statusColor(s.status, s.updated_at)}>{s.status}</span>
          <span className="text-gray-600">{timeAgo(s.updated_at)}</span>
        </span>
      ))}
    </div>
  );
}
```

**Step 5: Integrate into ChatView**

In `ChatView.tsx`, add after the header div and before the messages scroll area:
```tsx
import { useStatus } from "@/hooks/useStatus";
import { StatusBar } from "@/components/StatusBar";

// Inside ChatView component:
const statuses = useStatus(isLive ? room : null);

// In the JSX, between header and messages:
<StatusBar statuses={statuses} />
```

**Step 6: Commit**
```bash
git add app/fe/src/types.ts app/fe/src/utils/timeAgo.ts app/fe/src/hooks/useStatus.ts app/fe/src/components/StatusBar.tsx app/fe/src/components/ChatView.tsx
git commit -m "feat: add StatusBar component with real-time status updates"
```

---

### Task 7: MCP E2E Tests

**Files:**
- Modify: `app/be/tests/test_integration.py`

**Step 1: Write E2E tests**

```python
@pytest.mark.anyio
async def test_status_round_trip():
    """E2E: init_room → update_status → get_team_status via MCP client."""
    from chatnut.app import app
    async with Client(app, raise_on_error=False) as client:
        room = await call(client, "init_room", {"project": "e2e", "name": "status-e2e"})

        await call(client, "update_status", {
            "room_id": room["id"], "sender": "agent-1", "status": "Starting review"
        })
        await call(client, "update_status", {
            "room_id": room["id"], "sender": "agent-2", "status": "Running analysis"
        })

        result = await call(client, "get_team_status", {"room_id": room["id"]})
        assert len(result["statuses"]) == 2

        # Update existing status (UPSERT)
        await call(client, "update_status", {
            "room_id": room["id"], "sender": "agent-1", "status": "Completed"
        })
        result = await call(client, "get_team_status", {"room_id": room["id"]})
        agent1 = next(s for s in result["statuses"] if s["sender"] == "agent-1")
        assert agent1["status"] == "Completed"

@pytest.mark.anyio
async def test_update_status_nonexistent_room():
    """E2E: update_status on nonexistent room returns error."""
    from chatnut.app import app
    async with Client(app, raise_on_error=False) as client:
        result = await client.call_tool("update_status", {
            "room_id": "nonexistent", "sender": "agent", "status": "Working"
        })
        assert result.is_error

@pytest.mark.anyio
async def test_update_status_archived_room():
    """E2E: update_status on archived room returns error."""
    from chatnut.app import app
    async with Client(app, raise_on_error=False) as client:
        room = await call(client, "init_room", {"project": "e2e", "name": "archive-status"})
        await call(client, "archive_room", {"project": "e2e", "name": "archive-status"})
        result = await client.call_tool("update_status", {
            "room_id": room["id"], "sender": "agent", "status": "Working"
        })
        assert result.is_error
```

**Step 2: Commit**
```bash
git add app/be/tests/test_integration.py
git commit -m "test: add MCP E2E tests for status tools including error paths"
```

---

### Task 8: Frontend Tests

**Files:**
- Create: `app/fe/src/components/__tests__/StatusBar.test.tsx`

**Step 1: Write tests**

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatusBar } from "../StatusBar";

describe("StatusBar", () => {
  it("renders nothing when statuses is empty", () => {
    const { container } = render(<StatusBar statuses={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders sender names and statuses", () => {
    const statuses = [
      { sender: "reviewer-1", status: "Reviewing auth", updated_at: new Date().toISOString() },
      { sender: "codex", status: "Analyzing", updated_at: new Date().toISOString() },
    ];
    render(<StatusBar statuses={statuses} />);
    expect(screen.getByText("reviewer-1")).toBeDefined();
    expect(screen.getByText("Reviewing auth")).toBeDefined();
    expect(screen.getByText("codex")).toBeDefined();
    expect(screen.getByText("Analyzing")).toBeDefined();
  });

  it("shows 'now' for recent timestamps", () => {
    const statuses = [
      { sender: "agent", status: "Working", updated_at: new Date().toISOString() },
    ];
    render(<StatusBar statuses={statuses} />);
    expect(screen.getByText("now")).toBeDefined();
  });
});
```

**Step 2: Run tests**
```bash
cd app/fe && bun run test
```

**Step 3: Commit**
```bash
git add app/fe/src/components/__tests__/StatusBar.test.tsx
git commit -m "test: add StatusBar component tests"
```

---

### Task 9: Documentation Update

**Files:**
- Modify: `SKILL.md`
- Modify: `CLAUDE.md`

**Changes to SKILL.md:**

1. Add `update_status` and `get_team_status` to the MCP Tools table
2. Add `team_name` param to `init_room` signature
3. Update the Teammate Instructions block to include:
   - ToolSearch step: "Use ToolSearch to load chatnut tools: `ToolSearch(query: '+chatnut')`"
   - Disk-based room discovery: "Read room_id from `~/.claude/teams/{team_name}/chatroom.json` (written by `init_room` when `team_name` is provided)"
   - Status reporting: "Post status updates at task transitions via `update_status`"
4. Fix fallback text from `mcp__agents-chat` to `mcp__chatnut` (already done in working copy)

**Changes to CLAUDE.md:**

1. Add `room_status` table to the Schema section
2. Add `update_status` and `get_team_status` to the Tools table
3. Add `GET /api/chatrooms/{room_id}/status` and `GET /api/stream/status` to REST Endpoints table
4. Add design decision: "**Decoupled status system** — `room_status` table is separate from `messages`; UPSERT semantics (one row per sender per room); frontend shows as a StatusBar above messages, not inline"

**Commit:**
```bash
git add SKILL.md CLAUDE.md
git commit -m "docs: update SKILL.md and CLAUDE.md with status tools and room discovery"
```

---

## Verification

```bash
# Backend: full test suite
cd app/be && uv run pytest -xvs

# Frontend: typecheck + tests + build
cd app/fe && bun run tsc --noEmit && bun run test && bun run build
```

Expected: All backend tests pass, frontend typechecks, frontend tests pass, single-file build succeeds.

## AI Review Findings

| Severity | Source | Finding | Action |
|----------|--------|---------|--------|
| Critical | Architect + Backend | Migration path `chatnut/migrations/` wrong → `app/be/migrations/` | Fixed in Task 1 |
| Critical | Architect + Backend | `self._conn` → `self.db` throughout | Fixed in Task 2 |
| Critical | Architect + Backend | Test patterns use nonexistent `client` fixture | Fixed: Tasks 3-4 use direct-call pattern |
| Critical | Backend | `delete_room_statuses()` orphaned | Fixed: added to `db.delete_room()` in Task 1 |
| Critical | Backend | `conn.commit()` → `with conn:` | Fixed in Task 1 |
| Critical | Architect + Backend | `_write_team_chatroom` needs try/except | Fixed in Task 4 |
| Critical | Frontend | `useStatus` memory leak on reconnect | Fixed: `esRef` + `retryRef` pattern in Task 6 |
| Critical | Frontend | `_status_waiters` breaks layered architecture | Fixed: Task 5 uses polling (consistent with existing SSE) |
| Warning | Backend | No `MAX_STATUS_WAITERS_PER_ROOM` limit | N/A: waiters removed from routes; MCP tools don't use waiters for SSE |
| Warning | Backend | Status text length unconstrained | Fixed: `CHECK(length(status) <= 500)` in Task 1 |
| Warning | Backend | Routes use `create_router()` factory | Fixed in Task 5 |
| Warning | Frontend | `sticky top-0` has no effect | Fixed: removed in Task 6 |
| Warning | Frontend | `timeAgo` duplicates `formatTimestamp` | Fixed: extracted to `utils/timeAgo.ts` in Task 6 |
| Warning | Frontend | Color inconsistency — use `text-yellow-500` | Fixed in Task 6 |
| Warning | Frontend | No frontend tests | Fixed: added Task 8 |
| Critical | Codex + Gemini | Path traversal in `_write_team_chatroom` — `../../` escapes dir | Fixed: `os.path.basename()` sanitization + rejection test in Task 4 |
| Critical | Codex + Gemini | `is_disconnected()` must be `await`ed (Starlette async) | Fixed: `await is_disconnected()` in Task 5 |
| Suggestion | Architect | Status TTL/staleness cleanup | Noted: frontend dims after 5m; DB cleanup deferred |
| Suggestion | Backend | `clear_status` tool for removing entries | Deferred — not needed for MVP |
