# Deferred Performance & Test Fixes Implementation Plan

## Context

Code review identified four deferred issues in team-chat-mcp: N+1 queries in the chatroom SSE endpoint (3N queries per poll per client), blocking synchronous DB calls inside async SSE generators, `check_same_thread=False` without thread synchronization primitives, and zero frontend test coverage. These issues affect performance under concurrent SSE clients and leave the frontend untested.

## Goal

Eliminate the N+1 query pattern with batch SQL, wrap sync DB calls in async thread offloading, and establish frontend test infrastructure with initial hook tests.

## Architecture

Backend changes are contained within the existing layered architecture: `db.py` gets a new batch stats function, `service.py` exposes the batch method (and removes the now-unused per-room method), and `routes.py` wraps sync calls with `anyio.to_thread.run_sync()` in a single thread hop per poll cycle. Thread safety relies on SQLite WAL mode + `busy_timeout=5000` (already configured) — no Python-level lock needed. Frontend gets vitest + testing-library setup with tests for the two SSE hooks.

## Affected Areas

- Backend: `app/be/team_chat_mcp/db.py`, `service.py`, `routes.py`, `pyproject.toml`
- Backend tests: `app/be/tests/test_db.py`, `test_service.py`, `test_routes.py`
- Frontend: `app/fe/package.json`, `app/fe/vitest.config.ts`, `app/fe/src/hooks/__tests__/`

## Key Files

- `app/be/team_chat_mcp/db.py` — batch stats query, remove per-room stats
- `app/be/team_chat_mcp/routes.py` — single-hop async thread offloading + batch stats
- `app/be/team_chat_mcp/service.py` — expose batch stats, remove per-room stats
- `app/be/tests/test_db.py` — batch stats tests (replace per-room stats tests)
- `app/fe/src/hooks/__tests__/helpers.ts` — shared MockEventSource for frontend tests

## Reusable Utilities

- `app/be/team_chat_mcp/db.py:get_room_stats()` — existing per-room pattern (to be replaced)
- `app/be/team_chat_mcp/db.py:_row_to_room()` — existing row conversion pattern
- `app/be/tests/conftest.py:db` — in-memory SQLite fixture

---

## Tasks

### Task 1: Batch room stats query in db.py

**Files:**
- Modify: `app/be/team_chat_mcp/db.py`
- Test: `app/be/tests/test_db.py`

**Step 1: Write the failing test**

Add to `app/be/tests/test_db.py`:

```python
from team_chat_mcp.db import get_all_room_stats


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
    assert s1["last_message_content"] == "world"
    assert s1["role_counts"] == {"alice": 1, "bob": 1}

    s2 = stats[r2.id]
    assert s2["message_count"] == 2
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
```

**Step 2: Run test — expect FAIL**
```bash
cd app/be && uv run pytest tests/test_db.py::test_get_all_room_stats -xvs
```
Expected: `ImportError: cannot import name 'get_all_room_stats' from 'team_chat_mcp.db'`

**Step 3: Implement minimal code**

Add to `app/be/team_chat_mcp/db.py`:

```python
def get_all_room_stats(conn: sqlite3.Connection, room_ids: list[str]) -> dict[str, dict]:
    """Get message stats for multiple rooms in batch (3 queries total, not 3N).

    Returns a dict keyed by room_id with stats matching get_room_stats() output:
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
```

**Step 4: Run test — expect PASS**
```bash
cd app/be && uv run pytest tests/test_db.py::test_get_all_room_stats tests/test_db.py::test_get_all_room_stats_empty_rooms tests/test_db.py::test_get_all_room_stats_mixed tests/test_db.py::test_get_all_room_stats_empty_list -xvs
```

**Step 5: Commit**
```bash
git add app/be/team_chat_mcp/db.py app/be/tests/test_db.py
git commit -m "feat: add batch get_all_room_stats to eliminate N+1 queries"
```

---

### Task 2: Service layer batch stats + remove unused per-room stats

**Files:**
- Modify: `app/be/team_chat_mcp/service.py`
- Modify: `app/be/team_chat_mcp/db.py` (remove `get_room_stats`)
- Modify: `app/be/tests/test_service.py`
- Modify: `app/be/tests/test_db.py` (remove per-room stats tests)

**Step 1: Write the failing test**

Add to `app/be/tests/test_service.py`:

```python
def test_get_all_room_stats(svc):
    svc.post_message("proj", "room1", "alice", "hello")
    svc.post_message("proj", "room1", "bob", "world")
    svc.post_message("proj", "room2", "carol", "hi")

    rooms = svc.list_rooms(project="proj")
    room_ids = [r["id"] for r in rooms["rooms"]]
    stats = svc.get_all_room_stats(room_ids)

    assert len(stats) == 2
    for rid in room_ids:
        assert "message_count" in stats[rid]
        assert "role_counts" in stats[rid]
```

**Step 2: Run test — expect FAIL**
```bash
cd app/be && uv run pytest tests/test_service.py::test_get_all_room_stats -xvs
```
Expected: `AttributeError: 'ChatService' object has no attribute 'get_all_room_stats'`

**Step 3: Implement minimal code**

In `app/be/team_chat_mcp/service.py`:
- Add import: `from team_chat_mcp.db import get_all_room_stats as db_get_all_room_stats`
- Remove import: `get_room_stats as db_get_room_stats`
- Add method to `ChatService`:
  ```python
  def get_all_room_stats(self, room_ids: list[str]) -> dict[str, dict]:
      return db_get_all_room_stats(self.db, room_ids)
  ```
- Delete method: `ChatService.get_room_stats()`

In `app/be/team_chat_mcp/db.py`:
- Delete function `get_room_stats()` (lines 220-252) — fully replaced by `get_all_room_stats()`

In `app/be/tests/test_db.py`:
- Remove import of `get_room_stats`
- Delete `test_get_room_stats` and `test_get_room_stats_empty_room` tests

In `app/be/tests/test_service.py`:
- Delete `test_get_room_stats` (if it exists) — replaced by `test_get_all_room_stats`

**Step 4: Run test — expect PASS**
```bash
cd app/be && uv run pytest tests/test_service.py tests/test_db.py -xvs
```

**Step 5: Commit**
```bash
git add app/be/team_chat_mcp/db.py app/be/team_chat_mcp/service.py app/be/tests/test_db.py app/be/tests/test_service.py
git commit -m "refactor: replace per-room get_room_stats with batch get_all_room_stats"
```

---

### Task 3: Async SSE generators with single-hop thread offloading + batch stats

**Depends on:** Task 1, Task 2

**Files:**
- Modify: `app/be/team_chat_mcp/routes.py`
- Modify: `app/be/pyproject.toml` (add anyio dependency)
- Test: `app/be/tests/test_routes.py` (existing tests validate)

**Step 1: Add anyio as explicit dependency**

In `app/be/pyproject.toml`, add to dependencies:
```toml
dependencies = [
    "fastmcp>=2.0.0",
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.34.0",
    "sse-starlette>=2.0.0",
    "anyio>=4.0",
]
```

**Step 2: Implement the async refactor**

Replace the SSE generators in `app/be/team_chat_mcp/routes.py`:

```python
# Replace: import asyncio
# With: import anyio
import anyio

# ... keep hashlib, json, typing imports ...

async def message_event_generator(
    svc,
    room_id: str,
    last_id: int = 0,
    is_disconnected=None,
) -> AsyncIterator[dict]:
    """Async generator for SSE message events.

    Yields initial history (if last_id == 0) then polls for new messages.
    DB calls are offloaded to a thread to avoid blocking the event loop.
    """
    keepalive_counter = 0

    if last_id == 0:
        result = await anyio.to_thread.run_sync(
            lambda: svc.read_messages_by_room_id(room_id, limit=1000)
        )
        for msg in result["messages"]:
            yield {"id": str(msg["id"]), "data": json.dumps(msg)}
            last_id = msg["id"]

    while True:
        if is_disconnected and await is_disconnected():
            break
        result = await anyio.to_thread.run_sync(
            lambda lid=last_id: svc.read_messages_by_room_id(room_id, since_id=lid, limit=100)
        )
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
        await anyio.sleep(POLL_INTERVAL)


async def chatroom_event_generator(
    svc,
    project: str | None = None,
    branch: str | None = None,
    is_disconnected=None,
) -> AsyncIterator[dict]:
    """Async generator for SSE chatroom list events.

    Uses batch stats query (3 queries total) instead of per-room stats (3N queries).
    DB calls are offloaded to a single thread hop per poll cycle.
    """
    last_hash = ""
    keepalive_counter = 0
    while True:
        if is_disconnected and await is_disconnected():
            break

        # Single thread hop: list rooms + batch stats together
        def _fetch_rooms_with_stats():
            result = svc.list_rooms(status="all", project=project, branch=branch)
            rooms = result["rooms"]
            room_ids = [r["id"] for r in rooms]
            stats = svc.get_all_room_stats(room_ids) if room_ids else {}
            return rooms, stats

        rooms, all_stats = await anyio.to_thread.run_sync(_fetch_rooms_with_stats)
        active = [r for r in rooms if r["status"] == "live"]
        archived = [r for r in rooms if r["status"] == "archived"]

        # Enrich rooms with stats
        for room_dict in active + archived:
            stats = all_stats.get(room_dict["id"], {})
            room_dict["messageCount"] = stats.get("message_count", 0)
            room_dict["lastMessage"] = stats.get("last_message_content")
            room_dict["lastMessageTs"] = stats.get("last_message_ts")
            room_dict["roleCounts"] = stats.get("role_counts", {})

        payload = json.dumps({"active": active, "archived": archived}, sort_keys=True)
        content_hash = hashlib.sha256(payload.encode()).hexdigest()
        if content_hash != last_hash:
            last_hash = content_hash
            keepalive_counter = 0
            yield {"data": payload}
        else:
            keepalive_counter += 1
            if keepalive_counter >= int(KEEPALIVE_INTERVAL / POLL_INTERVAL):
                keepalive_counter = 0
                yield {"comment": "keepalive"}

        await anyio.sleep(POLL_INTERVAL)
```

**Step 3: Run ALL existing tests — expect PASS**
```bash
cd app/be && uv run pytest tests/test_routes.py tests/test_db.py tests/test_service.py -xvs
```

All existing SSE generator tests (test_stream_messages_initial_history, test_stream_messages_last_event_id, test_chatroom_event_generator_initial_emission, test_chatroom_event_generator_no_reemit_unchanged) must still pass. The `anyio.to_thread.run_sync` works with in-memory SQLite + `check_same_thread=False`.

**Step 4: Commit**
```bash
git add app/be/team_chat_mcp/routes.py app/be/pyproject.toml
git commit -m "perf: single-hop async thread offloading + batch stats in SSE generators"
```

---

### Task 4: Frontend test infrastructure

**Files:**
- Modify: `app/fe/package.json`
- Create: `app/fe/vitest.config.ts`
- Create: `app/fe/src/hooks/__tests__/helpers.ts`
- Create: `app/fe/src/hooks/__tests__/useSSE.test.ts`
- Create: `app/fe/src/hooks/__tests__/useChatrooms.test.ts`

**Step 1: Add test dependencies**

Update `app/fe/package.json` scripts and devDependencies:
```json
{
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "devDependencies": {
    "vitest": "^3.0.0",
    "@testing-library/react": "^16.0.0",
    "@testing-library/dom": "^10.0.0",
    "@testing-library/jest-dom": "^6.0.0",
    "jsdom": "^25.0.0",
    "@vitejs/plugin-react": "^4.5.2",
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "typescript": "~5.8.2",
    "vite": "^6.2.0",
    "vite-plugin-singlefile": "^2.0.3"
  }
}
```

**Step 2: Create vitest config**

Create `app/fe/vitest.config.ts`:
```typescript
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
  },
});
```

**Step 3: Create shared test helper**

Create `app/fe/src/hooks/__tests__/helpers.ts`:
```typescript
/**
 * Shared MockEventSource for SSE hook tests.
 * Supports onopen, onmessage, onerror, addEventListener, and test helpers.
 */
export class MockEventSource {
  url: string;
  onopen: ((e: Event) => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  readyState = 0;
  private listeners: Record<string, EventListener[]> = {};

  constructor(url: string) {
    this.url = url;
  }

  addEventListener(type: string, listener: EventListener) {
    (this.listeners[type] ??= []).push(listener);
  }

  removeEventListener(type: string, listener: EventListener) {
    this.listeners[type] = (this.listeners[type] ?? []).filter(
      (l) => l !== listener
    );
  }

  close() {
    this.readyState = 2;
  }

  // --- Test helpers ---

  /** Simulate a message event (triggers onmessage) */
  _emit(data: string) {
    this.onmessage?.(new MessageEvent("message", { data }));
  }

  /** Simulate a named event (triggers addEventListener listeners) */
  _emitNamed(type: string) {
    for (const listener of this.listeners[type] ?? []) {
      listener(new Event(type));
    }
  }

  /** Simulate connection open */
  _triggerOpen() {
    this.readyState = 1;
    this.onopen?.(new Event("open"));
  }

  /** Simulate connection error */
  _triggerError() {
    this.onerror?.(new Event("error"));
  }
}
```

**Step 4: Write useSSE tests**

Create `app/fe/src/hooks/__tests__/useSSE.test.ts`:
```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useSSE } from "../useSSE";
import { MockEventSource } from "./helpers";

let lastCreatedES: MockEventSource | null = null;

beforeEach(() => {
  lastCreatedES = null;
  vi.stubGlobal(
    "EventSource",
    class extends MockEventSource {
      constructor(url: string) {
        super(url);
        lastCreatedES = this;
      }
    }
  );
  // Synchronous RAF for predictable test behavior
  vi.stubGlobal("requestAnimationFrame", (cb: () => void) => {
    cb();
    return 0;
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useSSE", () => {
  it("returns empty messages and disconnected when roomId is null", () => {
    const { result } = renderHook(() => useSSE(null));
    expect(result.current.messages).toEqual([]);
    expect(result.current.connectionStatus).toBe("disconnected");
  });

  it("connects to SSE endpoint with room ID", () => {
    const { result } = renderHook(() => useSSE("room-123"));
    expect(result.current.connectionStatus).toBe("connecting");
    expect(lastCreatedES?.url).toContain("room_id=room-123");
  });

  it("transitions to connected on open", () => {
    const { result } = renderHook(() => useSSE("room-123"));

    act(() => {
      lastCreatedES?._triggerOpen();
    });

    expect(result.current.connectionStatus).toBe("connected");
  });

  it("accumulates messages from SSE events", () => {
    const { result } = renderHook(() => useSSE("room-123"));

    act(() => {
      lastCreatedES?._emit(
        JSON.stringify({
          id: 1,
          room_id: "room-123",
          sender: "alice",
          content: "hello",
          message_type: "message",
          created_at: "2026-01-01T00:00:00Z",
          metadata: null,
        })
      );
    });

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0].sender).toBe("alice");
  });

  it("clears messages on reset event", () => {
    const { result } = renderHook(() => useSSE("room-123"));

    // Add a message first
    act(() => {
      lastCreatedES?._emit(
        JSON.stringify({
          id: 1,
          room_id: "room-123",
          sender: "alice",
          content: "hello",
          message_type: "message",
          created_at: "2026-01-01T00:00:00Z",
          metadata: null,
        })
      );
    });
    expect(result.current.messages).toHaveLength(1);

    // Fire reset event
    act(() => {
      lastCreatedES?._emitNamed("reset");
    });
    expect(result.current.messages).toEqual([]);
  });

  it("clears messages on room change", () => {
    const { result, rerender } = renderHook(
      ({ roomId }) => useSSE(roomId),
      { initialProps: { roomId: "room-1" as string | null } }
    );

    act(() => {
      lastCreatedES?._emit(
        JSON.stringify({
          id: 1,
          room_id: "room-1",
          sender: "alice",
          content: "hello",
          message_type: "message",
          created_at: "2026-01-01T00:00:00Z",
          metadata: null,
        })
      );
    });
    expect(result.current.messages).toHaveLength(1);

    rerender({ roomId: "room-2" });
    expect(result.current.messages).toEqual([]);
  });

  it("sets connecting status on error and retries", () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useSSE("room-123"));
    const firstES = lastCreatedES;

    act(() => {
      firstES?._triggerError();
    });

    expect(result.current.connectionStatus).toBe("connecting");

    // Advance past the 3-second retry delay
    act(() => {
      vi.advanceTimersByTime(3000);
    });

    // A new EventSource should have been created
    expect(lastCreatedES).not.toBe(firstES);
    vi.useRealTimers();
  });
});
```

**Step 5: Write useChatrooms tests**

Create `app/fe/src/hooks/__tests__/useChatrooms.test.ts`:
```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useChatrooms } from "../useChatrooms";
import { MockEventSource } from "./helpers";

let lastCreatedES: MockEventSource | null = null;

beforeEach(() => {
  lastCreatedES = null;
  vi.stubGlobal(
    "EventSource",
    class extends MockEventSource {
      constructor(url: string) {
        super(url);
        lastCreatedES = this;
      }
    }
  );
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useChatrooms", () => {
  it("starts in loading state", () => {
    const { result } = renderHook(() => useChatrooms());
    expect(result.current.loading).toBe(true);
    expect(result.current.active).toEqual([]);
    expect(result.current.archived).toEqual([]);
  });

  it("connects to SSE with project filter", () => {
    renderHook(() => useChatrooms("my-project"));
    expect(lastCreatedES?.url).toContain("project=my-project");
  });

  it("connects without filter when no project", () => {
    renderHook(() => useChatrooms());
    expect(lastCreatedES?.url).not.toContain("project=");
  });

  it("parses SSE data into active and archived rooms", () => {
    const { result } = renderHook(() => useChatrooms());

    act(() => {
      lastCreatedES?._emit(
        JSON.stringify({
          active: [
            { id: "1", name: "dev", project: "proj", status: "live", messageCount: 5 },
          ],
          archived: [
            { id: "2", name: "old", project: "proj", status: "archived" },
          ],
        })
      );
    });

    expect(result.current.loading).toBe(false);
    expect(result.current.active).toHaveLength(1);
    expect(result.current.active[0].name).toBe("dev");
    expect(result.current.archived).toHaveLength(1);
  });

  it("resets state when project changes", () => {
    const { result, rerender } = renderHook(
      ({ project }) => useChatrooms(project),
      { initialProps: { project: "proj-a" as string | undefined } }
    );

    rerender({ project: "proj-b" });
    expect(result.current.loading).toBe(true);
    expect(result.current.active).toEqual([]);
  });

  it("retries connection on error", () => {
    vi.useFakeTimers();
    renderHook(() => useChatrooms());
    const firstES = lastCreatedES;

    act(() => {
      firstES?._triggerError();
    });

    // Advance past the 3-second retry delay
    act(() => {
      vi.advanceTimersByTime(3000);
    });

    // A new EventSource should have been created
    expect(lastCreatedES).not.toBe(firstES);
    vi.useRealTimers();
  });
});
```

**Step 6: Install and run tests**
```bash
cd app/fe && bun install && bun run test
```
Expected: All tests pass.

**Step 7: Commit**
```bash
git add app/fe/package.json app/fe/vitest.config.ts app/fe/src/hooks/__tests__/
git commit -m "test: add vitest + testing-library frontend test infrastructure with hook tests"
```

---

### Task 5: Documentation Update

- [ ] Update DESIGN.md key decisions: batch stats replaces per-room stats, anyio thread offloading for SSE
- [ ] Update CLAUDE.md commands section: add `cd app/fe && bun run test` for frontend tests
- [ ] Add `bun run test` to verification commands

---

## Verification

```bash
# Backend tests (all existing + new)
cd app/be && uv run pytest -xvs

# Frontend tests
cd app/fe && bun run test

# Type check frontend
cd app/fe && npx tsc --noEmit

# Build frontend
cd app/fe && bun run build
```

Expected: All backend tests pass (existing + new batch stats), all frontend tests pass, TypeScript compiles, frontend builds.

## AI Review Findings

| Severity | Source | Finding | Action |
|----------|--------|---------|--------|
| Critical | Architect, Backend Dev, QA | Task 1 test assertion: room2 last_message should be "joined" (system msg has highest id) | Fixed — test now asserts "joined" with explanatory comment |
| Critical | All reviewers | Task 2 (threading lock) was dead code — never acquired by production code | Dropped entirely — SQLite WAL + busy_timeout=5000 provides thread safety |
| Critical | Frontend Dev | Missing @testing-library/dom peer dependency | Added to devDependencies |
| Warning | Gemini | Double thread hop in chatroom_event_generator adds unnecessary latency | Fixed — combined into single _fetch_rooms_with_stats() function |
| Warning | Backend Dev | asyncio.sleep should be anyio.sleep for consistency | Fixed — replaced with anyio.sleep |
| Warning | Architect, Backend Dev | anyio should be explicit dependency in pyproject.toml | Added anyio>=4.0 |
| Warning | Backend Dev | get_room_stats becomes dead code after batch replacement | Integrated cleanup into Task 2 |
| Warning | QA, Backend Dev | Task 4 new chatroom test duplicates existing tests | Removed — existing tests validate the refactor |
| Warning | Frontend Dev | Duplicate MockEventSource classes should be shared | Created shared helpers.ts |
| Warning | Frontend Dev, QA, Gemini | Missing reset event and error/reconnection tests | Added to both useSSE and useChatrooms tests |
| Warning | Frontend Dev | globals:true in vitest config is redundant with explicit imports | Removed globals:true |
| Suggestion | QA | Mixed empty/non-empty room test for batch stats | Added test_get_all_room_stats_mixed |
| Suggestion | Gemini | SQL IN clause 999-variable limit should be documented | Added docstring note |
| Suggestion | Frontend Dev | Consider happy-dom over jsdom for speed | Noted — jsdom is standard, can switch later |
