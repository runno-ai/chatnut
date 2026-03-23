# Backend Reliability Implementation Plan

## Context

Two backend reliability issues (MCP-21, MCP-22) were identified during architecture review. MCP-21 covers a server startup race condition in `_ensure_server()`, a misleadingly named lock, and undocumented single-worker assumptions. MCP-22 covers missing `ON DELETE CASCADE` on the messages FK, a silent UUID discard in `create_room()`, and timestamp format fragility in `_now()`.

## Goal

Fix all 6 sub-issues across MCP-21 and MCP-22 to improve backend reliability, with full test coverage.

## Architecture

Use `fcntl.flock()` on a dedicated lock file to serialize concurrent `_ensure_server()` calls (Unix-only, consistent with existing `start_new_session=True` usage). Rename `svc.lock` to `_wait_notify_lock` and move it to `mcp.py` as a module-level lock since it's only consumed there — it serializes the wait/notify handoff only, not general ChatService concurrency. Add a SQLite migration to rebuild the `messages` table with `ON DELETE CASCADE`, preserving AUTOINCREMENT sequence. Add debug logging to `create_room()` for UUID discards and enforce explicit `+00:00` timestamp format via `strftime`.

## Affected Areas

- Backend: `chatnut/cli.py`, `chatnut/mcp.py`, `chatnut/service.py`, `chatnut/db.py`, `chatnut/migrations/`

## Key Files

- `app/be/chatnut/cli.py` — `_ensure_server()` race condition fix with `fcntl.flock`
- `app/be/chatnut/mcp.py` — Lock moved here as module-level `_wait_notify_lock`
- `app/be/chatnut/service.py` — Remove `self.lock`, update references
- `app/be/chatnut/db.py` — UUID discard logging, timestamp format enforcement, `_now()` used consistently
- `app/be/chatnut/migrations/004_messages_cascade.sql` — FK CASCADE migration with sequence preservation

## Reusable Utilities

- `app/be/chatnut/migrate.py:run_migrations()` — Handles numbered SQL migration files atomically
- `app/be/chatnut/db.py:_now()` — Centralized timestamp generation (to be hardened)
- `app/be/chatnut/db.py:create_room()` — Existing UUID generation + INSERT OR IGNORE pattern
- `app/be/tests/conftest.py:db` — In-memory SQLite fixture for testing

---

## Tasks

### Task 1: Fix `_ensure_server()` race condition with `fcntl.flock`

**Files:**
- Modify: `app/be/chatnut/cli.py:116-150`
- Test: `app/be/tests/test_cli.py`

**Step 1: Write the failing test**

```python
# In test_cli.py, add to TestEnsureServer class:

def test_ensure_server_acquires_flock(self, tmp_path, monkeypatch):
    """_ensure_server acquires fcntl.flock(LOCK_EX) on lock file."""
    monkeypatch.setenv("CHATNUT_RUN_DIR", str(tmp_path))

    from chatnut.cli import _ensure_server

    def fake_popen(*args, **kwargs):
        (tmp_path / "server.port").write_text("8888")
        return MagicMock()

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    import fcntl
    flock_calls = []
    original_flock = fcntl.flock

    def tracking_flock(fd, operation):
        flock_calls.append(operation)
        return original_flock(fd, operation)

    with patch("chatnut.cli.subprocess.Popen", side_effect=fake_popen), \
         patch("chatnut.cli.httpx.get", side_effect=[
             httpx.ConnectError("refused"),
             mock_resp,
         ]), \
         patch("chatnut.cli.time.sleep"), \
         patch("chatnut.cli.fcntl.flock", side_effect=tracking_flock):
        _ensure_server()

    assert (tmp_path / "server.lock").exists()
    # Verify LOCK_EX was acquired and LOCK_UN was released
    assert fcntl.LOCK_EX in flock_calls
    assert fcntl.LOCK_UN in flock_calls


def test_ensure_server_lock_file_created(self, tmp_path, monkeypatch):
    """_ensure_server creates a lock file for flock coordination."""
    monkeypatch.setenv("CHATNUT_RUN_DIR", str(tmp_path))

    from chatnut.cli import _ensure_server

    def fake_popen(*args, **kwargs):
        (tmp_path / "server.port").write_text("8888")
        return MagicMock()

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("chatnut.cli.subprocess.Popen", side_effect=fake_popen), \
         patch("chatnut.cli.httpx.get", side_effect=[
             httpx.ConnectError("refused"),
             mock_resp,
         ]), \
         patch("chatnut.cli.time.sleep"):
        _ensure_server()

    assert (tmp_path / "server.lock").exists()
```

**Step 2: Run test — expect FAIL**
```bash
cd app/be && uv run pytest tests/test_cli.py::TestEnsureServer::test_ensure_server_lock_file_created -xvs
```
Expected: FAIL — no lock file created yet, `fcntl` not imported.

**Step 3: Implement minimal code**

In `cli.py`, add `import fcntl` to imports and modify `_ensure_server()`:

```python
import fcntl

def _ensure_server() -> str:
    """Ensure the HTTP server is running. Returns the server URL.

    Uses fcntl.flock on a lock file to prevent concurrent startup races
    when multiple CLI sessions call _ensure_server() simultaneously.
    This is Unix-only, consistent with start_new_session=True in Popen.
    """
    if _is_server_running():
        url = _get_server_url()
        if url:
            return url

    run_dir = _get_run_dir()
    run_dir.mkdir(parents=True, exist_ok=True)

    lock_file = run_dir / "server.lock"
    lock_fh = open(lock_file, "w")  # noqa: SIM115
    try:
        fcntl.flock(lock_fh, fcntl.LOCK_EX)

        # Re-check after acquiring lock — another process may have started the server
        if _is_server_running():
            url = _get_server_url()
            if url:
                return url

        # Redirect server output to a log file for debugging
        log_file = run_dir / "server.log"
        log_fh = open(log_file, "a")  # noqa: SIM115
        try:
            subprocess.Popen(
                [sys.executable, "-m", "chatnut.cli", "serve"],
                stdout=log_fh,
                stderr=log_fh,
                start_new_session=True,
            )
        finally:
            log_fh.close()

        port_file = run_dir / "server.port"
        for _ in range(20):
            time.sleep(0.5)
            if port_file.exists():
                url = _get_server_url()
                if url:
                    try:
                        resp = httpx.get(f"{url}/api/status", timeout=2)
                        if resp.status_code == 200:
                            return url
                    except Exception:
                        continue

        raise RuntimeError("Failed to start chatnut server within 10 seconds")
    finally:
        fcntl.flock(lock_fh, fcntl.LOCK_UN)
        lock_fh.close()
```

**Step 4: Run test — expect PASS**
```bash
cd app/be && uv run pytest tests/test_cli.py::TestEnsureServer -xvs
```

**Step 5: Commit**
```bash
git add app/be/chatnut/cli.py app/be/tests/test_cli.py
git commit -m "fix(cli): prevent _ensure_server race with fcntl.flock (MCP-21)"
```

---

### Task 2: Rename `svc.lock` to `_wait_notify_lock` and move to `mcp.py`

**Files:**
- Modify: `app/be/chatnut/mcp.py:193,265`
- Modify: `app/be/chatnut/service.py:36`
- Test: `app/be/tests/test_service.py`, `app/be/tests/test_mcp.py`

**Step 1: Write the failing test**

```python
# In test_service.py, add:
def test_chat_service_no_lock_attribute(db):
    """ChatService should not expose a generic 'lock' attribute."""
    from chatnut.service import ChatService
    svc = ChatService(db)
    assert not hasattr(svc, "lock")


# In test_mcp.py, add:
def test_wait_notify_lock_exists():
    """mcp module should expose _wait_notify_lock for post/wait synchronization."""
    from chatnut import mcp
    assert hasattr(mcp, "_wait_notify_lock")
    import threading
    assert isinstance(mcp._wait_notify_lock, type(threading.Lock()))
```

**Step 2: Run test — expect FAIL**
```bash
cd app/be && uv run pytest tests/test_service.py::test_chat_service_no_lock_attribute tests/test_mcp.py::test_wait_notify_lock_exists -xvs
```
Expected: FAIL — `svc.lock` still exists, `_wait_notify_lock` doesn't exist yet.

**Step 3: Implement minimal code**

In `service.py`, remove `self.lock = threading.Lock()` from `__init__` and remove the `import threading`:

```python
# Remove line 3: import threading
# Remove line 36: self.lock = threading.Lock()
```

In `mcp.py`, add `import threading` and module-level lock after `_waiters`:

```python
import threading

# Serializes post_message insert+notify with wait_for_messages' _read() closure.
# This ensures that a message inserted by post_message is visible to _read() before
# _notify_waiters fires. Without this lock, _read() could execute between INSERT and
# notify, see no new messages, then miss the notification.
# Only used in post_message() and wait_for_messages() — other write paths don't need it
# because they don't interact with the waiter notification system.
# Intentionally module-level (not per-ChatService): one server process = one lock.
_wait_notify_lock = threading.Lock()
```

Update `post_message` tool:
```python
with _wait_notify_lock:
    result = svc.post_message_by_room_id(room_id, sender, content, message_type=message_type)
```

Update `_read` in `wait_for_messages`:
```python
def _read():
    with _wait_notify_lock:
        return svc.read_messages_by_room_id(
            room_id, since_id=since_id, limit=limit, message_type=message_type
        )
```

**Step 4: Run test — expect PASS**
```bash
cd app/be && uv run pytest -xvs
```

**Step 5: Commit**
```bash
git add app/be/chatnut/mcp.py app/be/chatnut/service.py app/be/tests/test_service.py app/be/tests/test_mcp.py
git commit -m "refactor(mcp): rename svc.lock to _wait_notify_lock, move to mcp.py (MCP-21)"
```

---

### Task 3: Document single-worker requirement

**Files:**
- Modify: `CLAUDE.md`
- Modify: `app/be/chatnut/app.py` (startup log)
- Test: `app/be/tests/test_app_startup.py`

**Step 1: Write the failing test**

```python
# In test_app_startup.py, add:
import logging
import pytest

@pytest.mark.anyio
async def test_startup_logs_single_worker_note(caplog):
    """Startup lifespan should log a note about single-worker requirement."""
    from chatnut.app import app

    with caplog.at_level(logging.INFO):
        async with app.router.lifespan_context(app):
            pass

    single_worker_logs = [
        r for r in caplog.records
        if "single-worker" in r.message.lower() or "single worker" in r.message.lower()
    ]
    assert len(single_worker_logs) >= 1, (
        f"Expected a single-worker log message, got: {[r.message for r in caplog.records]}"
    )
```

**Step 2: Run test — expect FAIL**
```bash
cd app/be && uv run pytest tests/test_app_startup.py::test_startup_logs_single_worker_note -xvs
```

**Step 3: Implement minimal code**

In `app.py` lifespan function, add after the existing startup log:
```python
logger.info(
    "chatnut requires single-worker mode (uvicorn only, not gunicorn multi-worker). "
    "The wait_for_messages notification system uses process-local asyncio.Queue objects "
    "that cannot communicate across worker processes."
)
```

In `CLAUDE.md`, add to Design Decisions:
```markdown
- **Single-worker only** — `_waiters` (asyncio.Queue per waiter) are process-local. Multi-worker deployment (e.g. gunicorn with multiple workers) breaks `wait_for_messages` silently — notifications from one worker are invisible to waiters in another. Always run with `uvicorn` directly, never behind a multi-worker process manager.
```

**Step 4: Run test — expect PASS**
```bash
cd app/be && uv run pytest tests/test_app_startup.py -xvs
```

**Step 5: Commit**
```bash
git add app/be/chatnut/app.py CLAUDE.md app/be/tests/test_app_startup.py
git commit -m "docs: document single-worker requirement (MCP-21)"
```

---

### Task 4: Add `ON DELETE CASCADE` to messages FK

**Files:**
- Create: `app/be/chatnut/migrations/004_messages_cascade.sql`
- Modify: `app/be/chatnut/db.py:138-146` (simplify `delete_room`)
- Test: `app/be/tests/test_db.py`

**Step 1: Write the failing test**

```python
# In test_db.py, add:
def test_messages_cascade_on_room_delete(db):
    """Messages should be automatically deleted when their room is deleted via CASCADE."""
    room = create_room(db, project="proj", name="cascade-test")
    insert_message(db, room.id, "alice", "hello")
    insert_message(db, room.id, "bob", "world")

    # Archive then delete directly via SQL to test CASCADE behavior
    db.execute("UPDATE rooms SET status='archived', archived_at=datetime('now') WHERE id=?", (room.id,))
    db.commit()
    db.execute("DELETE FROM rooms WHERE id=?", (room.id,))
    db.commit()

    # Messages should be gone via CASCADE
    msgs, _ = get_messages(db, room.id)
    assert len(msgs) == 0
```

**Step 2: Run test — expect FAIL**
```bash
cd app/be && uv run pytest tests/test_db.py::test_messages_cascade_on_room_delete -xvs
```
Expected: FAIL — FK violation or messages orphaned (no CASCADE).

**Step 3: Implement minimal code**

Create migration `004_messages_cascade.sql` with explicit column list and sequence preservation:
```sql
-- 004_messages_cascade.sql: Add ON DELETE CASCADE to messages FK.
-- SQLite cannot ALTER foreign keys, so we rebuild the table.
-- Columns are listed explicitly (not SELECT *) to prevent breakage on schema changes.

-- Preserve AUTOINCREMENT sequence to avoid ID reuse after row deletions
CREATE TABLE messages_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    sender TEXT NOT NULL,
    content TEXT NOT NULL,
    message_type TEXT NOT NULL DEFAULT 'message',
    created_at TEXT NOT NULL,
    metadata TEXT
);

INSERT INTO messages_new (id, room_id, sender, content, message_type, created_at, metadata)
    SELECT id, room_id, sender, content, message_type, created_at, metadata FROM messages;

-- Transfer AUTOINCREMENT sequence before dropping old table
INSERT OR REPLACE INTO sqlite_sequence (name, seq)
    SELECT 'messages_new', seq FROM sqlite_sequence WHERE name = 'messages';

DROP TABLE messages;

ALTER TABLE messages_new RENAME TO messages;

-- sqlite_sequence entry for 'messages_new' is now 'messages' after rename
-- Clean up any stale 'messages_new' entry
DELETE FROM sqlite_sequence WHERE name = 'messages_new';

CREATE INDEX IF NOT EXISTS idx_messages_room ON messages(room_id, id);
```

Simplify `delete_room()` in `db.py`:
```python
def delete_room(conn: sqlite3.Connection, room_id: str) -> int:
    """Delete a room and all its messages. Returns number of messages deleted.

    Messages, read cursors, and room statuses are deleted via ON DELETE CASCADE.
    We count messages before deletion for the return value.
    Note: TOCTOU between COUNT and DELETE is harmless — archived rooms reject
    new messages at the service layer, so the count cannot increase.
    """
    with conn:
        msg_count = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE room_id=?", (room_id,)
        ).fetchone()[0]
        conn.execute("DELETE FROM rooms WHERE id=?", (room_id,))
    return msg_count
```

**Step 4: Run test — expect PASS**
```bash
cd app/be && uv run pytest tests/test_db.py -xvs
```

**Step 5: Commit**
```bash
git add app/be/chatnut/migrations/004_messages_cascade.sql app/be/chatnut/db.py app/be/tests/test_db.py
git commit -m "fix(db): add ON DELETE CASCADE to messages FK (MCP-22)"
```

---

### Task 5: Log debug message on UUID discard in `create_room()`

**Files:**
- Modify: `app/be/chatnut/db.py:50-69`
- Test: `app/be/tests/test_db.py`

**Step 1: Write the failing test**

```python
# In test_db.py, add:
def test_create_room_idempotent_logs_discarded_uuid(db, caplog):
    """create_room logs at DEBUG level when a generated UUID is discarded."""
    import logging
    with caplog.at_level(logging.DEBUG):
        r1 = create_room(db, project="proj", name="dedup-test")
        r2 = create_room(db, project="proj", name="dedup-test")

    assert r1.id == r2.id
    # The second call generates a new UUID that gets discarded — should log
    discard_logs = [r for r in caplog.records if "discarded" in r.message.lower()]
    assert len(discard_logs) >= 1
```

**Step 2: Run test — expect FAIL**
```bash
cd app/be && uv run pytest tests/test_db.py::test_create_room_idempotent_logs_discarded_uuid -xvs
```

**Step 3: Implement minimal code**

In `db.py`, add logging import and logger at module level, then add the check to `create_room()`:

```python
import logging

logger = logging.getLogger(__name__)
```

In `create_room()`, after `_row_to_room(row)`, add:
```python
    room = _row_to_room(row)
    if room.id != room_id:
        logger.debug(
            "create_room: room '%s/%s' already exists (id=%s), discarded generated UUID %s",
            project, name, room.id, room_id,
        )
    return room
```

**Step 4: Run test — expect PASS**
```bash
cd app/be && uv run pytest tests/test_db.py::test_create_room_idempotent_logs_discarded_uuid -xvs
```

**Step 5: Commit**
```bash
git add app/be/chatnut/db.py app/be/tests/test_db.py
git commit -m "fix(db): log at debug level when create_room discards UUID (MCP-22)"
```

---

### Task 6: Enforce `+00:00` timestamp format in `_now()` and use consistently

**Files:**
- Modify: `app/be/chatnut/db.py:34-35,276-278`
- Test: `app/be/tests/test_db.py`

**Step 1: Write the failing test**

```python
# In test_db.py, add:
def test_now_always_uses_plus_zero_offset():
    """_now() must always produce +00:00 suffix, never Z."""
    from chatnut.db import _now
    timestamp = _now()
    assert timestamp.endswith("+00:00"), f"Expected +00:00 suffix, got: {timestamp}"
    assert "Z" not in timestamp
    assert "T" in timestamp  # ISO 8601 format


def test_now_roundtrip_string_comparison():
    """Timestamps from _now() must compare correctly as strings."""
    import time as time_mod
    from chatnut.db import _now
    t1 = _now()
    time_mod.sleep(0.01)
    t2 = _now()
    assert t2 > t1  # String comparison must be chronological
```

**Step 2: Run test — expect PASS** (current impl already produces `+00:00`)
```bash
cd app/be && uv run pytest tests/test_db.py::test_now_always_uses_plus_zero_offset tests/test_db.py::test_now_roundtrip_string_comparison -xvs
```

These tests codify the existing correct behavior. The hardening makes it explicit:

**Step 3: Implement minimal code**

In `db.py`, replace `_now()`:

```python
def _now() -> str:
    """Return current UTC time in ISO 8601 format with explicit +00:00 offset.

    Uses strftime to guarantee the +00:00 suffix. datetime.isoformat() also produces
    this for UTC-aware datetimes, but an explicit format string makes the contract
    visible and prevents accidental regressions.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")
```

Also update `auto_archive_stale_rooms` (db.py:276) to use `_now()`-consistent formatting for the cutoff:

```python
def auto_archive_stale_rooms(conn: sqlite3.Connection, max_inactive_seconds: int = 7200) -> list[Room]:
    cutoff = datetime.fromtimestamp(
        datetime.now(timezone.utc).timestamp() - max_inactive_seconds, tz=timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")
    now = _now()
    # ... rest unchanged
```

**Step 4: Run test — expect PASS**
```bash
cd app/be && uv run pytest tests/test_db.py -xvs
```

**Step 5: Commit**
```bash
git add app/be/chatnut/db.py app/be/tests/test_db.py
git commit -m "fix(db): enforce explicit +00:00 timestamp format in _now() (MCP-22)"
```

---

### Phase 7: Documentation Update

- [x] CLAUDE.md: single-worker requirement documented (Task 3)
- [x] Docstring for `_ensure_server()` updated with lock explanation (Task 1)
- [x] Docstring for `_wait_notify_lock` explaining its narrow scope (Task 2)
- [x] Docstring for `_now()` explaining format guarantee (Task 6)
- [x] Docstring for `delete_room()` updated to mention CASCADE (Task 4)

All docstrings are included in their respective task implementations above.

---

## Verification

```bash
cd app/be && uv run pytest -xvs
```

Expected: All tests pass, including:
- `test_ensure_server_acquires_flock` and `test_ensure_server_lock_file_created` in `test_cli.py`
- `test_chat_service_no_lock_attribute` in `test_service.py`
- `test_wait_notify_lock_exists` in `test_mcp.py`
- `test_startup_logs_single_worker_note` in `test_app_startup.py`
- `test_messages_cascade_on_room_delete` in `test_db.py`
- `test_create_room_idempotent_logs_discarded_uuid` in `test_db.py`
- `test_now_always_uses_plus_zero_offset` and `test_now_roundtrip_string_comparison` in `test_db.py`
- All existing tests unchanged

## AI Review Findings

| Severity | Source | Finding | Action |
|----------|--------|---------|--------|
| Critical | architect, backend-dev, codex | Task 1 original test didn't test concurrency — tested sequential re-entry | Replaced with `test_ensure_server_acquires_flock` that mocks and verifies `fcntl.flock(LOCK_EX)` is called |
| Critical | architect, backend-dev | Task 4 migration AUTOINCREMENT counter regression risk on table rebuild | Added `sqlite_sequence` preservation in migration SQL |
| Critical | codex | Task 4 migration used fragile `SELECT *` | Replaced with explicit column list in INSERT |
| Warning | architect, backend-dev, codex | Task 3 test was brittle (inspect.getsource) | Replaced with anyio lifespan test + caplog |
| Warning | backend-dev | Task 2 missing companion test for lock in mcp.py | Added `test_wait_notify_lock_exists` |
| Warning | architect, codex | Task 6 `auto_archive_stale_rooms` inconsistent timestamp format | Updated cutoff to use same `strftime` format |
| Warning | architect | Task 4 `delete_room` TOCTOU between COUNT and DELETE | Added comment explaining harmlessness for archived rooms |
| Warning | codex | Task 5 plan text said "log warning" but code uses `logger.debug` | Fixed plan text to "log at debug level" |
| Warning | minimax | Task 1 `log_fh` not closed in finally if Popen raises | Wrapped Popen in try/finally for log_fh |
| Warning | minimax | Task 2 lock/service pairing assumption | Already documented in lock scope comment |
| Suggestion | architect, codex | Task 2 add scope comment to module-level lock | Added "Intentionally module-level" comment |
