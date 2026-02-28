# Unread/Read System Implementation Plan

## Context

Team Chat MCP has no concept of read state. Agents and the web UI cannot tell which messages are new since their last visit. This makes it hard to track active conversations in rooms with many messages. An unread/read system lets each reader (agent or browser) know exactly how many new messages exist per room.

## Goal

Add per-reader unread message tracking with read cursors, exposed via MCP tools, REST endpoints, SSE enrichment, and frontend unread badges.

## Architecture

A new `read_cursors` table stores `(room_id, reader, last_read_message_id)` tuples. Readers advance their cursor by calling a "mark as read" endpoint. Unread counts are computed as `COUNT(messages WHERE id > cursor)` using the existing autoincrement message IDs. The SSE chatroom stream includes per-reader unread counts, and the sidebar displays unread badges.

## Affected Areas

- Backend: `db.py`, `service.py`, `mcp.py`, `routes.py`, `migrations/`
- Frontend: `Sidebar.tsx`, `ChatView.tsx`, `useChatrooms.ts`, `App.tsx`, `types.ts`

## Key Files

- `app/be/team_chat_mcp/db.py` — Core DB functions for read cursors and unread counts
- `app/be/team_chat_mcp/service.py` — Business logic: mark_read, get_unread_counts
- `app/be/team_chat_mcp/routes.py` — REST endpoint + SSE enrichment with reader param
- `app/fe/src/components/Sidebar.tsx` — Unread badge rendering on room items
- `app/fe/src/hooks/useChatrooms.ts` — Pass reader identity to SSE stream

## Reusable Utilities

- `app/be/team_chat_mcp/db.py:get_all_room_stats()` — Batch stats pattern (3 queries, not 3N) to follow for unread counts
- `app/be/team_chat_mcp/db.py:_escape_like()` — SQL escaping helper
- `app/be/team_chat_mcp/migrate.py:run_migrations()` — Numbered migration runner
- `app/be/team_chat_mcp/db.py:_now()` / `_new_id()` — Timestamp and UUID helpers

---

## Tasks

### Task 1: Database Migration + Read Cursor DB Functions

**Files:**
- Create: `app/be/migrations/002_read_cursors.sql`
- Modify: `app/be/team_chat_mcp/db.py`
- Test: `app/be/tests/test_db.py`

**Step 1: Write the failing test**

Add to `app/be/tests/test_db.py`:

```python
from team_chat_mcp.db import (
    create_room, insert_message, upsert_read_cursor,
    get_read_cursor, get_unread_counts,
)


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
    from team_chat_mcp.db import delete_read_cursors
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
```

**Step 2: Run test — expect FAIL**
```bash
cd app/be && uv run pytest tests/test_db.py -xvs -k "read_cursor or unread_count"
```
Expected: `ImportError: cannot import name 'upsert_read_cursor'`

**Step 3: Implement minimal code**

Create `app/be/migrations/002_read_cursors.sql`:

```sql
CREATE TABLE IF NOT EXISTS read_cursors (
    room_id TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    reader TEXT NOT NULL,
    last_read_message_id INTEGER NOT NULL DEFAULT 0 CHECK(last_read_message_id >= 0),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (room_id, reader)
);
```

Add to `app/be/team_chat_mcp/db.py`:

```python
def upsert_read_cursor(
    conn: sqlite3.Connection,
    room_id: str,
    reader: str,
    last_read_message_id: int,
) -> None:
    """Set or advance a reader's cursor. Cursor only moves forward."""
    now = _now()
    with conn:
        conn.execute(
            """INSERT INTO read_cursors (room_id, reader, last_read_message_id, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(room_id, reader) DO UPDATE
               SET last_read_message_id = MAX(last_read_message_id, excluded.last_read_message_id),
                   updated_at = CASE WHEN excluded.last_read_message_id > last_read_message_id
                                     THEN excluded.updated_at ELSE updated_at END""",
            (room_id, reader, last_read_message_id, now),
        )


def get_read_cursor(
    conn: sqlite3.Connection,
    room_id: str,
    reader: str,
) -> int | None:
    """Get a reader's cursor position. Returns None if no cursor exists."""
    row = conn.execute(
        "SELECT last_read_message_id FROM read_cursors WHERE room_id=? AND reader=?",
        (room_id, reader),
    ).fetchone()
    return row[0] if row else None


def get_unread_counts(
    conn: sqlite3.Connection,
    room_ids: list[str],
    reader: str,
) -> dict[str, int]:
    """Get unread message counts for multiple rooms for a given reader.

    Uses a single query: LEFT JOIN read_cursors to get each room's cursor,
    then COUNT messages with id > cursor (or all messages if no cursor).
    Returns dict keyed by room_id → unread count (0 for rooms with no messages).
    """
    if not room_ids:
        return {}

    placeholders = ",".join("?" * len(room_ids))
    rows = conn.execute(
        f"""SELECT m.room_id, COUNT(*) as unread
            FROM messages m
            LEFT JOIN read_cursors rc
              ON m.room_id = rc.room_id AND rc.reader = ?
            WHERE m.room_id IN ({placeholders})
              AND m.id > COALESCE(rc.last_read_message_id, 0)
            GROUP BY m.room_id""",
        [reader, *room_ids],
    ).fetchall()

    result = {rid: 0 for rid in room_ids}
    for row in rows:
        result[row[0]] = row[1]
    return result


def delete_read_cursors(conn: sqlite3.Connection, room_id: str) -> None:
    """Delete all read cursors for a room. Used by delete_room and clear_room."""
    with conn:
        conn.execute("DELETE FROM read_cursors WHERE room_id = ?", (room_id,))
```

Also update `delete_room()` in `db.py` to explicitly call `delete_read_cursors(conn, room_id)` before deleting the room (belt-and-suspenders with ON DELETE CASCADE).

Also update `delete_messages()` (used by `clear_room`) to call `delete_read_cursors(conn, room_id)` since cursors pointing to deleted messages are meaningless.

**Step 4: Run test — expect PASS**
```bash
cd app/be && uv run pytest tests/test_db.py -xvs -k "read_cursor or unread_count"
```

**Step 5: Commit**
```bash
git add app/be/migrations/002_read_cursors.sql app/be/team_chat_mcp/db.py app/be/tests/test_db.py
git commit -m "feat(be): add read_cursors table and db functions for unread tracking"
```

---

### Task 2: Service Layer — mark_read and get_unread_counts

**Files:**
- Modify: `app/be/team_chat_mcp/service.py`
- Test: `app/be/tests/test_service.py`

**Step 1: Write the failing test**

Add to `app/be/tests/test_service.py`:

```python
def test_mark_read(db):
    """mark_read advances cursor and returns updated position."""
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    m1 = svc.post_message("proj", "dev", "alice", "hello")
    m2 = svc.post_message("proj", "dev", "alice", "world")
    result = svc.mark_read(room["id"], "bob", m2["id"])
    assert result["room_id"] == room["id"]
    assert result["reader"] == "bob"
    assert result["last_read_message_id"] == m2["id"]


def test_mark_read_nonexistent_room(db):
    svc = ChatService(db)
    with pytest.raises(ValueError, match="not found"):
        svc.mark_read("nonexistent", "bob", 1)


def test_get_unread_counts(db):
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
```

**Step 2: Run test — expect FAIL**
```bash
cd app/be && uv run pytest tests/test_service.py -xvs -k "mark_read or unread_count"
```
Expected: `AttributeError: 'ChatService' object has no attribute 'mark_read'`

**Step 3: Implement minimal code**

Add to `app/be/team_chat_mcp/service.py`:

```python
# Add imports at top:
from team_chat_mcp.db import (
    # ... existing imports ...
    upsert_read_cursor,
    get_read_cursor,
    get_unread_counts as db_get_unread_counts,
)

# Add methods to ChatService:
def mark_read(self, room_id: str, reader: str, last_read_message_id: int) -> dict:
    """Mark messages as read up to the given message ID for a reader."""
    room_obj = get_room_by_id(self.db, room_id)
    if room_obj is None:
        raise ValueError(f"Room '{room_id}' not found")
    upsert_read_cursor(self.db, room_id, reader, last_read_message_id)
    cursor = get_read_cursor(self.db, room_id, reader)
    return {"room_id": room_id, "reader": reader, "last_read_message_id": cursor}

def get_unread_counts(self, room_ids: list[str], reader: str) -> dict[str, int]:
    """Get unread message counts for multiple rooms for a given reader."""
    return db_get_unread_counts(self.db, room_ids, reader)
```

**Step 4: Run test — expect PASS**
```bash
cd app/be && uv run pytest tests/test_service.py -xvs -k "mark_read or unread_count"
```

**Step 5: Commit**
```bash
git add app/be/team_chat_mcp/service.py app/be/tests/test_service.py
git commit -m "feat(be): add mark_read and get_unread_counts to ChatService"
```

---

### Task 3: MCP Tool — mark_read

**Files:**
- Modify: `app/be/team_chat_mcp/mcp.py`
- Test: `app/be/tests/test_mcp.py`

**Step 1: Write the failing test**

Note: `test_mcp.py` only has `test_all_tools_registered` using `mcp.list_tools()`. There is no `call_tool` helper or MCP client fixture. Since the MCP tool is a one-line wrapper over `ChatService.mark_read()`, we verify the tool is registered and test the actual logic through the service layer (already covered in Task 2).

Add to `app/be/tests/test_mcp.py`:

```python
@pytest.mark.anyio
async def test_mark_read_tool_registered():
    """Verify mark_read is in the tool list."""
    from team_chat_mcp.mcp import mcp
    tools = await mcp.list_tools()
    tool_names = [t.name for t in tools]
    assert "mark_read" in tool_names
```

**Step 2: Run test — expect FAIL**
```bash
cd app/be && uv run pytest tests/test_mcp.py -xvs -k "mark_read"
```

**Step 3: Implement minimal code**

Add to `app/be/team_chat_mcp/mcp.py`:

```python
@mcp.tool()
def mark_read(
    room_id: str,
    reader: str,
    last_read_message_id: int,
) -> dict:
    """Mark messages as read up to the given message ID for a reader. Cursor only moves forward."""
    return _get_service().mark_read(room_id, reader, last_read_message_id)
```

**Step 4: Run test — expect PASS**
```bash
cd app/be && uv run pytest tests/test_mcp.py -xvs -k "mark_read"
```

**Step 5: Commit**
```bash
git add app/be/team_chat_mcp/mcp.py app/be/tests/test_mcp.py
git commit -m "feat(be): add mark_read MCP tool"
```

---

### Task 4: REST Endpoint — Mark Read + SSE Unread Enrichment

**Files:**
- Modify: `app/be/team_chat_mcp/routes.py`
- Test: `app/be/tests/test_routes.py`

**Step 1: Write the failing test**

Add to `app/be/tests/test_routes.py`:

```python
def test_mark_read_endpoint(client, svc):
    room = svc.init_room("proj", "dev")
    msg = svc.post_message("proj", "dev", "alice", "hello")
    resp = client.post(
        f"/api/chatrooms/{room['id']}/read",
        json={"reader": "web-user", "last_read_message_id": msg["id"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["reader"] == "web-user"
    assert data["last_read_message_id"] == msg["id"]


def test_mark_read_nonexistent_room(client):
    resp = client.post(
        "/api/chatrooms/nonexistent/read",
        json={"reader": "web-user", "last_read_message_id": 1},
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_chatroom_sse_includes_unread_count(db):
    """SSE chatroom stream includes unreadCount when reader param is present."""
    from team_chat_mcp.routes import chatroom_event_generator
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    svc.post_message("proj", "dev", "alice", "msg1")
    svc.post_message("proj", "dev", "alice", "msg2")

    gen = chatroom_event_generator(svc, reader="web-user")
    event = await gen.__anext__()
    rooms = json.loads(event["data"])
    active = rooms["active"]
    assert len(active) == 1
    assert active[0]["unreadCount"] == 2  # web-user hasn't read anything
    await gen.aclose()
```

**Step 2: Run test — expect FAIL**
```bash
cd app/be && uv run pytest tests/test_routes.py -xvs -k "mark_read"
```

**Step 3: Implement minimal code**

Add to `app/be/team_chat_mcp/routes.py` inside `create_router()`:

```python
from pydantic import BaseModel

class MarkReadRequest(BaseModel):
    reader: str
    last_read_message_id: int

@router.post("/chatrooms/{room_id}/read")
def mark_read(room_id: str, body: MarkReadRequest):
    try:
        return get_service().mark_read(room_id, body.reader, body.last_read_message_id)
    except ValueError as e:
        msg = str(e)
        status = 404 if "not found" in msg else 422
        raise HTTPException(status_code=status, detail=msg) from e
```

Update `chatroom_event_generator` to accept a `reader` parameter and enrich rooms with unread counts.

**CRITICAL (thread safety):** The `get_unread_counts` call MUST go inside the `_fetch_rooms_with_stats` closure (which runs in `anyio.to_thread.run_sync()`), NOT in the async generator body. SQLite connections are not thread-safe across async boundaries.

```python
async def chatroom_event_generator(
    svc,
    project: str | None = None,
    branch: str | None = None,
    reader: str | None = None,
    is_disconnected=None,
) -> AsyncIterator[dict]:
    # ... existing code ...
    # Inside _fetch_rooms_with_stats closure (runs in thread):
    def _fetch_rooms_with_stats():
        # ... existing room + stats fetching ...
        # Add unread counts inside the same closure:
        if reader and room_ids:
            unread = db_get_unread_counts(svc.db, room_ids, reader)
            for room_dict in active + archived:
                room_dict["unreadCount"] = unread.get(room_dict["id"], 0)
        return active, archived
```

Update `stream_chatrooms` route to accept `reader` query param:

```python
@router.get("/stream/chatrooms")
async def stream_chatrooms(
    request: Request,
    project: str | None = None,
    branch: str | None = None,
    reader: str | None = None,
):
    svc = get_service()
    gen = chatroom_event_generator(
        svc, project=project, branch=branch, reader=reader,
        is_disconnected=request.is_disconnected,
    )
    return EventSourceResponse(gen)
```

**Step 4: Run test — expect PASS**
```bash
cd app/be && uv run pytest tests/test_routes.py -xvs -k "mark_read"
```

**Step 5: Commit**
```bash
git add app/be/team_chat_mcp/routes.py app/be/tests/test_routes.py
git commit -m "feat(be): add mark-read REST endpoint and SSE unread enrichment"
```

---

### Task 5: Frontend — Unread Badges + Auto Mark-Read

**Files:**
- Modify: `app/fe/src/types.ts`
- Modify: `app/fe/src/hooks/useChatrooms.ts`
- Modify: `app/fe/src/components/Sidebar.tsx`
- Modify: `app/fe/src/components/ChatView.tsx`
- Modify: `app/fe/src/App.tsx`

**Step 1: Write the failing test** (N/A — frontend tests are integration-level, this task is UI wiring)

**Step 2: Implement**

**`app/fe/src/types.ts`** — add `unreadCount` to `ChatroomInfo`:

```typescript
export interface ChatroomInfo {
  // ... existing fields ...
  unreadCount?: number;
}
```

**`app/fe/src/hooks/useChatrooms.ts`** — pass `reader` to SSE stream:

```typescript
export function useChatrooms(project?: string, reader?: string) {
  // ... existing state ...

  useEffect(() => {
    // ... existing setup ...
    function connect() {
      if (closed) return;
      const params = new URLSearchParams();
      if (project) params.set("project", project);
      if (reader) params.set("reader", reader);
      const qs = params.toString();
      es = new EventSource(`/api/stream/chatrooms${qs ? `?${qs}` : ""}`);
      // ... rest unchanged ...
    }
    // ...
  }, [project, reader]);

  return { active, archived, loading };
}
```

**`app/fe/src/App.tsx`** — define reader ID and pass to hook + ChatView:

```typescript
const READER_ID = "web-ui";

// In App component:
const { active, archived, loading } = useChatrooms(
  selectedProject ?? undefined,
  READER_ID
);

// Pass to ChatView:
<ChatView
  room={selectedRoom}
  roomName={...}
  isLive={isLive}
  reader={READER_ID}
/>
```

**`app/fe/src/components/Sidebar.tsx`** — render unread badge on `RoomItem`:

In the `RoomItem` component, after the room name span, add:

```tsx
{room.unreadCount != null && room.unreadCount > 0 && (
  <span className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 text-[10px] font-bold rounded-full bg-blue-500 text-white">
    {room.unreadCount > 99 ? "99+" : room.unreadCount}
  </span>
)}
```

**`app/fe/src/components/ChatView.tsx`** — auto mark-read when viewing messages:

Add `reader` prop. When the room is selected and messages load, POST to `/api/chatrooms/{room_id}/read` with the latest message ID:

```typescript
interface ChatViewProps {
  room: string | null;
  roomName: string | null;
  isLive: boolean;
  reader?: string;
}

// Inside component, after messages update:
// Only mark as read when user is at the bottom of the scroll area.
// This prevents marking messages as read when the user is scrolled up reading history.
const [isAtBottom, setIsAtBottom] = useState(true);

// Track scroll position:
const handleScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
  const el = e.currentTarget;
  const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  setIsAtBottom(atBottom);
}, []);

useEffect(() => {
  if (!room || !reader || messages.length === 0 || !isAtBottom) return;
  const lastMsg = messages[messages.length - 1];
  fetch(`/api/chatrooms/${encodeURIComponent(room)}/read`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reader, last_read_message_id: lastMsg.id }),
  }).catch(() => {}); // fire-and-forget
}, [room, reader, messages.length, isAtBottom]);
```

**Step 3: Build and verify**
```bash
cd app/fe && bun run build
```

**Step 4: Commit**
```bash
git add app/fe/src/types.ts app/fe/src/hooks/useChatrooms.ts app/fe/src/components/Sidebar.tsx app/fe/src/components/ChatView.tsx app/fe/src/App.tsx
git commit -m "feat(fe): add unread badges and auto mark-read on room view"
```

---

### Task 6: Integration Test — Full Round-Trip

**Files:**
- Modify: `app/be/tests/test_integration.py`

**Step 1: Write the test**

```python
def test_unread_read_round_trip(db):
    """Full round-trip: post messages → check unread → mark read → check unread again."""
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    svc.post_message("proj", "dev", "alice", "msg1")
    svc.post_message("proj", "dev", "alice", "msg2")
    m3 = svc.post_message("proj", "dev", "alice", "msg3")

    # Before reading: all 3 unread
    counts = svc.get_unread_counts([room["id"]], "bob")
    assert counts[room["id"]] == 3

    # Mark read up to msg3
    svc.mark_read(room["id"], "bob", m3["id"])

    # After reading: 0 unread
    counts = svc.get_unread_counts([room["id"]], "bob")
    assert counts[room["id"]] == 0

    # New message arrives
    svc.post_message("proj", "dev", "alice", "msg4")

    # 1 unread
    counts = svc.get_unread_counts([room["id"]], "bob")
    assert counts[room["id"]] == 1


def test_unread_counts_multi_reader(db):
    """Different readers have independent cursors."""
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    m1 = svc.post_message("proj", "dev", "alice", "msg1")
    svc.post_message("proj", "dev", "alice", "msg2")

    svc.mark_read(room["id"], "bob", m1["id"])

    bob_counts = svc.get_unread_counts([room["id"]], "bob")
    carol_counts = svc.get_unread_counts([room["id"]], "carol")
    assert bob_counts[room["id"]] == 1    # read msg1, msg2 unread
    assert carol_counts[room["id"]] == 2  # never read


def test_delete_room_cascades_read_cursors(db):
    """Deleting a room also deletes its read cursors (ON DELETE CASCADE)."""
    svc = ChatService(db)
    room = svc.init_room("proj", "dev")
    msg = svc.post_message("proj", "dev", "alice", "hello")
    svc.mark_read(room["id"], "bob", msg["id"])
    svc.archive_room("proj", "dev")
    svc.delete_room(room["id"])
    # Cursor should be gone (no orphaned data)
    from team_chat_mcp.db import get_read_cursor
    assert get_read_cursor(db, room["id"], "bob") is None
```

**Step 2: Run test — expect PASS** (implementation already done)
```bash
cd app/be && uv run pytest tests/test_integration.py -xvs -k "unread"
```

**Step 3: Commit**
```bash
git add app/be/tests/test_integration.py
git commit -m "test: add integration tests for unread/read round-trip"
```

---

### Phase 7: Documentation Update

Update:
- [ ] `CLAUDE.md` — add `mark_read` to Tools table, add `/api/chatrooms/{room_id}/read` to REST endpoints, add `reader` param to SSE, update schema
- [ ] `DESIGN.md` — add read_cursors to schema section, add mark_read to MCP tools table
- [ ] Docstrings for all new functions in `db.py`, `service.py`

---

## Verification

```bash
# Backend tests (all)
cd app/be && uv run pytest -xvs

# Frontend type check + tests + build
cd app/fe && bun run test && bun run build
```

Expected: All tests pass, build succeeds, no type errors.

## AI Review Findings

### Accepted Amendments

| # | Amendment | Source | Applied To |
|---|-----------|--------|------------|
| 1 | Remove unused `idx_read_cursors_reader` index | Architect | Task 1: migration |
| 2 | Conditional `updated_at` in UPSERT (only when cursor advances) | Architect | Task 1: `upsert_read_cursor` |
| 3 | Move `get_unread_counts` inside `_fetch_rooms_with_stats` closure | Architect | Task 4: SSE enrichment |
| 4 | Auto mark-read only when `isAtBottom` | Architect | Task 5: ChatView |
| 5 | Explicit `DELETE FROM read_cursors` in `delete_room()` | Architect | Task 1: `delete_read_cursors()` |
| 6 | `clear_room` should reset read cursors | Architect + Backend-dev | Task 1: `delete_read_cursors()` |
| 7 | Create separate `delete_read_cursors()` db function | Backend-dev | Task 1: new db function |
| 8 | `CHECK(last_read_message_id >= 0)` constraint | Codex + Backend-dev | Task 1: migration |
| 9 | Count ALL message types in unread counts | Architect | Task 1: no filter needed |
| 10 | MCP test: verify registration only (service-layer covers logic) | Backend-dev + Codex | Task 3: test approach |
| 11 | Add SSE unread enrichment test | Codex + Backend-dev | Task 4: new test |
| 12 | Add cross-room cursor isolation test | Codex + Backend-dev | Task 1: new test |

### Rejected Findings

| Finding | Source | Reason |
|---------|--------|--------|
| Server-assigned cursor (ignore client value) | Gemini | Over-engineering — no-auth trust model |
| Bounds check against MAX(messages.id) | Codex | Extra query, minimal value; CHECK >= 0 sufficient |

### Key Decision

**System messages in unread counts:** Count ALL message types. Rationale: simpler query, consistent behavior, avoids edge case where room shows 0 unread but has unread system messages. Recommended by architect, corroborated by backend-dev and codex.

### Reviewers

- **Architect** — 2 critical, 4 warnings. APPROVED with amendments.
- **Backend-dev** — 2 critical, 3 warnings. Thorough engagement with codex findings.
- **Gemini-reviewer** — 0 critical, 3 warnings, 4 suggestions. Architecture focus.
- **Codex-reviewer** — 3 critical, 4 warnings, 3 suggestions. Code correctness focus.
- **Frontend-dev** — No response (did not post review).
