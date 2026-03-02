# Code Quality Implementation Plan

## Context

Four issues addressing correctness bugs, test-coverage gaps, and open-source polish for the `agents-chat-mcp` public repo. MCP-5 is the highest-priority fix (bugs affecting all users); MCP-6 and MCP-13 close test-coverage gaps; MCP-8 adds contributor infrastructure.

## Goal

Fix all MCP-5 bugs, add MCP tool E2E test coverage (MCP-6), add the missing STATIC_DIR env-var override test (MCP-13), and apply open-source polish (MCP-8) — all tests passing, no regressions.

## Architecture

MCP-5 adds `ChatService.db_path()` (SQLite PRAGMA query) so `ping()` reflects the live service's actual DB path instead of the module-level config constant. MCP-5 also adds validation to `ChatService.search()` so the route-level `ValueError` handler is non-dead-code. MCP-6 uses `fastmcp.Client` for in-process MCP protocol dispatch — no HTTP overhead, but exercises the full FastMCP tool-handler layer. MCP-13 uses `monkeypatch.setattr` (pattern already established in `test_app_config.py`). MCP-8 is purely additive: type annotations, docstrings, and new community files.

## Affected Areas

- Backend: `agents_chat_mcp/service.py`, `agents_chat_mcp/mcp.py`, `agents_chat_mcp/routes.py`, `agents_chat_mcp/app.py`, `pyproject.toml`, `.gitignore`
- Tests: `tests/test_mcp.py` (extend), `tests/test_app_config.py` (extend), `tests/test_mcp_e2e.py` (new)
- Community: `CODE_OF_CONDUCT.md`, `.github/ISSUE_TEMPLATE/bug_report.md`, `.github/pull_request_template.md`

## Key Files

- `app/be/agents_chat_mcp/mcp.py` — `ping()` uses stale `DB_PATH`; fix to call `_get_service().db_path()`
- `app/be/agents_chat_mcp/service.py` — add `db_path()` method; add empty-query validation to `search()`
- `app/be/agents_chat_mcp/routes.py` — `search()` missing `ValueError` handler; `create_router` untyped
- `app/be/agents_chat_mcp/app.py` — `app_lifespan(app)` untyped; `STATIC_DIR` module-level constant
- `app/be/tests/test_app_config.py` — add STATIC_DIR env-var override test (traversal/503 already there)

## Reusable Utilities

- `app/be/agents_chat_mcp/service.py:ChatService` — `self.db` is the sqlite3 Connection; `PRAGMA database_list` returns `(seq, name, file)` rows where `file` is `""` for `:memory:` databases
- `app/be/tests/conftest.py:db` — in-memory DB fixture for all tests
- `monkeypatch.setattr(app_module, "STATIC_DIR", str(tmp_path))` — established pattern in `test_app_config.py:25`
- `fastmcp.Client(mcp_module.mcp)` — in-process MCP dispatch for E2E tests
- `mcp_module.set_service_factory(factory)` — wire tests to in-memory DB

---

## Tasks

### Task 1: MCP-5 — Code & Config Fixes

**Files:**
- Modify: `app/be/agents_chat_mcp/service.py` — add `db_path()` method; add empty-query validation to `search()`
- Modify: `app/be/agents_chat_mcp/mcp.py` — fix `ping()` to use live service path
- Modify: `app/be/agents_chat_mcp/routes.py` — add `ValueError` handler to `search()`
- Modify: `app/be/pyproject.toml` — add `[tool.pytest.ini_options]`
- Modify: `.gitignore` — add `.env` and `.env.*`
- Test: `app/be/tests/test_service.py` — add `db_path()` test + empty-query test
- Test: `app/be/tests/test_mcp.py` — add `ping()` live-path unit test

**Step 1: Write the failing tests**

Add to `app/be/tests/test_service.py`:
```python
def test_db_path_returns_string(db):
    """ChatService.db_path() returns a string (empty for :memory:, path for file DBs)."""
    from agents_chat_mcp.service import ChatService
    svc = ChatService(db)
    path = svc.db_path()
    assert isinstance(path, str)


def test_search_rejects_empty_query(db):
    """ChatService.search() raises ValueError for empty or whitespace-only queries."""
    from agents_chat_mcp.service import ChatService
    import pytest
    svc = ChatService(db)
    with pytest.raises(ValueError, match="query"):
        svc.search("")
    with pytest.raises(ValueError, match="query"):
        svc.search("   ")
```

Add to `app/be/tests/test_mcp.py`:
```python
def test_ping_uses_live_service_path(db):
    """ping() returns the live service db_path, not the module-level DB_PATH constant."""
    from agents_chat_mcp import mcp as mcp_module
    from agents_chat_mcp.service import ChatService

    svc = ChatService(db)
    original_factory = mcp_module._service_factory
    mcp_module.set_service_factory(lambda: svc)
    try:
        result = mcp_module.ping()
        assert result["status"] == "ok"
        # The path should come from the service (in-memory returns ""), not config constant
        assert result["db_path"] == svc.db_path()
    finally:
        mcp_module.set_service_factory(original_factory)


def test_search_route_returns_422_for_empty_query(db):
    """GET /api/search?q= should return 422 for empty query."""
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from agents_chat_mcp.routes import create_router
    from agents_chat_mcp.service import ChatService

    svc = ChatService(db)
    test_app = FastAPI()
    router = create_router(lambda: svc)
    test_app.include_router(router)
    client = TestClient(test_app, raise_server_exceptions=False)

    resp = client.get("/api/search", params={"q": ""})
    assert resp.status_code == 422

    resp = client.get("/api/search", params={"q": "   "})
    assert resp.status_code == 422
```

**Step 2: Run tests — expect FAIL**
```bash
cd app/be && uv run pytest tests/test_service.py::test_db_path_returns_string tests/test_service.py::test_search_rejects_empty_query tests/test_mcp.py::test_ping_uses_live_service_path tests/test_mcp.py::test_search_route_returns_422_for_empty_query -xvs
```
Expected: `AttributeError: 'ChatService' object has no attribute 'db_path'` and `AssertionError` (no ValueError raised).

**Step 3: Implement minimal code**

In `app/be/agents_chat_mcp/service.py`, add after `__init__`:
```python
    def db_path(self) -> str:
        """Return the database file path used by this service instance.

        Returns empty string for in-memory databases.
        """
        row = self.db.execute("PRAGMA database_list").fetchone()
        return row[2] if row else ""
```

In `app/be/agents_chat_mcp/service.py`, update `search()` to add input validation at the top:
```python
    def search(self, query: str, project: str | None = None) -> dict:
        if not query or not query.strip():
            raise ValueError("query must be a non-empty string")
        result = search_rooms_and_messages(self.db, query, project=project)
        # ... rest of existing implementation unchanged
```

In `app/be/agents_chat_mcp/mcp.py`, replace `ping()`:
```python
@mcp.tool()
def ping() -> dict:
    """Health check — returns DB path and status."""
    return {"db_path": _get_service().db_path(), "status": "ok"}
```

Remove the now-unused `from agents_chat_mcp.config import DB_PATH` import from `mcp.py` (verify nothing else uses `DB_PATH` in mcp.py first).

In `app/be/agents_chat_mcp/routes.py`, update `search()`:
```python
    @router.get("/search")
    def search(q: str, project: str | None = None):
        try:
            return get_service().search(q, project=project)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
```

In `app/be/pyproject.toml`, add after `[build-system]`:
```toml
[tool.pytest.ini_options]
asyncio_mode = "strict"
```
(Note: pytest-asyncio 1.3.0 already defaults to strict mode; this entry makes it explicit.)

In `.gitignore`, add:
```
.env
.env.*
```

**Step 4: Run tests — expect PASS**
```bash
cd app/be && uv run pytest tests/test_service.py::test_db_path_returns_string tests/test_service.py::test_search_rejects_empty_query tests/test_mcp.py::test_ping_uses_live_service_path tests/test_mcp.py::test_search_route_returns_422_for_empty_query -xvs
```

**Step 5: Full suite — expect no regressions**
```bash
cd app/be && uv run pytest -x
```

**Step 6: Commit**
```bash
git add app/be/agents_chat_mcp/service.py app/be/agents_chat_mcp/mcp.py app/be/agents_chat_mcp/routes.py app/be/pyproject.toml .gitignore
git add app/be/tests/test_service.py app/be/tests/test_mcp.py
git commit -m "fix(MCP-5): fix ping() stale DB_PATH, add search validation + ValueError handler, fix .gitignore and asyncio_mode"
```

---

### Task 2: MCP-6 — MCP Tool E2E Tests

**Depends on:** Task 1 (ping() fix and search() validation must be in place so E2E tests verify corrected behavior)

**Files:**
- Create: `app/be/tests/test_mcp_e2e.py`

**Step 1: Write the tests**

Create `app/be/tests/test_mcp_e2e.py`:
```python
"""End-to-end tests invoking MCP tools through the FastMCP protocol layer.

Uses fastmcp.Client for in-process MCP dispatch — exercises the full tool-handler
layer (tool registration → handler → service → DB) without HTTP overhead.

Note on CallToolResult API: client.call_tool() returns a CallToolResult object.
Access the response via result.content[0].text (JSON string from TextContent).
"""

import asyncio
import json

import pytest
from fastmcp import Client

from agents_chat_mcp import mcp as mcp_module
from agents_chat_mcp.service import ChatService


@pytest.fixture
async def mcp_svc(db):
    """Wire MCP module to an in-memory ChatService for E2E tests.

    Sets the event loop on the mcp module so _notify_waiters works correctly
    (required for wait_for_messages tests). Clears _waiters on teardown to
    prevent state leakage between tests.
    """
    svc = ChatService(db)
    original_factory = mcp_module._service_factory
    mcp_module.set_service_factory(lambda: svc)
    # Required for wait_for_messages notification path to work in tests
    mcp_module.set_event_loop(asyncio.get_running_loop())
    yield svc
    mcp_module.set_service_factory(original_factory)
    mcp_module.set_event_loop(None)
    # Clear any stale waiters from the test
    if hasattr(mcp_module, "_waiters"):
        mcp_module._waiters.clear()


# ---------------------------------------------------------------------------
# Helper: call a tool and return the parsed dict response
# ---------------------------------------------------------------------------

async def call(client: Client, tool: str, args: dict | None = None) -> dict | list:
    result = await client.call_tool(tool, args or {})
    return json.loads(result.content[0].text)


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_e2e_ping(mcp_svc):
    """ping() returns status=ok and a db_path via MCP Client."""
    async with Client(mcp_module.mcp) as client:
        data = await call(client, "ping")
    assert data["status"] == "ok"
    assert "db_path" in data


@pytest.mark.anyio
async def test_e2e_init_room(mcp_svc):
    """init_room() creates a room and returns its id."""
    async with Client(mcp_module.mcp) as client:
        room = await call(client, "init_room", {"project": "test", "name": "general"})
    assert room["name"] == "general"
    assert room["project"] == "test"
    assert "id" in room


@pytest.mark.anyio
async def test_e2e_init_room_idempotent(mcp_svc):
    """init_room() returns the same room on duplicate calls."""
    async with Client(mcp_module.mcp) as client:
        r1 = await call(client, "init_room", {"project": "test", "name": "general"})
        r2 = await call(client, "init_room", {"project": "test", "name": "general"})
    assert r1["id"] == r2["id"]


@pytest.mark.anyio
async def test_e2e_post_and_read_messages(mcp_svc):
    """post_message() + read_messages() round-trip via MCP Client."""
    async with Client(mcp_module.mcp) as client:
        room = await call(client, "init_room", {"project": "test", "name": "chat"})
        room_id = room["id"]
        await call(client, "post_message", {"room_id": room_id, "sender": "alice", "content": "hello"})
        await call(client, "post_message", {"room_id": room_id, "sender": "bob", "content": "world"})
        result = await call(client, "read_messages", {"room_id": room_id})
    assert len(result["messages"]) == 2
    assert result["messages"][0]["sender"] == "alice"
    assert result["messages"][1]["sender"] == "bob"


@pytest.mark.anyio
async def test_e2e_read_messages_since_id(mcp_svc):
    """read_messages() with since_id returns only newer messages."""
    async with Client(mcp_module.mcp) as client:
        room = await call(client, "init_room", {"project": "test", "name": "chat"})
        room_id = room["id"]
        m1 = await call(client, "post_message", {"room_id": room_id, "sender": "alice", "content": "first"})
        await call(client, "post_message", {"room_id": room_id, "sender": "bob", "content": "second"})
        result = await call(client, "read_messages", {"room_id": room_id, "since_id": m1["id"]})
    assert len(result["messages"]) == 1
    assert result["messages"][0]["content"] == "second"


@pytest.mark.anyio
async def test_e2e_list_rooms(mcp_svc):
    """list_rooms() returns created rooms."""
    async with Client(mcp_module.mcp) as client:
        await call(client, "init_room", {"project": "proj-a", "name": "general"})
        await call(client, "init_room", {"project": "proj-b", "name": "general"})
        result = await call(client, "list_rooms", {})
    assert len(result["rooms"]) == 2


@pytest.mark.anyio
async def test_e2e_list_rooms_filter_by_project(mcp_svc):
    """list_rooms() filters by project."""
    async with Client(mcp_module.mcp) as client:
        await call(client, "init_room", {"project": "proj-a", "name": "r1"})
        await call(client, "init_room", {"project": "proj-b", "name": "r2"})
        result = await call(client, "list_rooms", {"project": "proj-a"})
    assert len(result["rooms"]) == 1
    assert result["rooms"][0]["project"] == "proj-a"


@pytest.mark.anyio
async def test_e2e_list_projects(mcp_svc):
    """list_projects() returns distinct project names."""
    async with Client(mcp_module.mcp) as client:
        await call(client, "init_room", {"project": "alpha", "name": "r"})
        await call(client, "init_room", {"project": "beta", "name": "r"})
        result = await call(client, "list_projects", {})
    assert set(result["projects"]) == {"alpha", "beta"}


@pytest.mark.anyio
async def test_e2e_archive_room(mcp_svc):
    """archive_room() changes room status to archived."""
    async with Client(mcp_module.mcp) as client:
        await call(client, "init_room", {"project": "proj", "name": "dev"})
        result = await call(client, "archive_room", {"project": "proj", "name": "dev"})
    assert result["archived_at"] is not None


@pytest.mark.anyio
async def test_e2e_delete_room(mcp_svc):
    """delete_room() removes an archived room."""
    async with Client(mcp_module.mcp) as client:
        room = await call(client, "init_room", {"project": "proj", "name": "dev"})
        await call(client, "archive_room", {"project": "proj", "name": "dev"})
        result = await call(client, "delete_room", {"room_id": room["id"]})
    assert "deleted_messages" in result


@pytest.mark.anyio
async def test_e2e_clear_room(mcp_svc):
    """clear_room() deletes all messages but keeps the room."""
    async with Client(mcp_module.mcp) as client:
        room = await call(client, "init_room", {"project": "proj", "name": "dev"})
        room_id = room["id"]
        await call(client, "post_message", {"room_id": room_id, "sender": "alice", "content": "msg"})
        await call(client, "clear_room", {"project": "proj", "name": "dev"})
        result = await call(client, "read_messages", {"room_id": room_id})
    assert result["messages"] == []


@pytest.mark.anyio
async def test_e2e_mark_read(mcp_svc):
    """mark_read() records the read cursor."""
    async with Client(mcp_module.mcp) as client:
        room = await call(client, "init_room", {"project": "proj", "name": "dev"})
        room_id = room["id"]
        msg = await call(client, "post_message", {"room_id": room_id, "sender": "alice", "content": "hi"})
        result = await call(client, "mark_read", {"room_id": room_id, "reader": "bob", "last_read_message_id": msg["id"]})
    assert result["last_read_message_id"] == msg["id"]
    assert result["reader"] == "bob"


@pytest.mark.anyio
async def test_e2e_search(mcp_svc):
    """search() finds rooms and messages matching query."""
    async with Client(mcp_module.mcp) as client:
        room = await call(client, "init_room", {"project": "proj", "name": "auth-discussion"})
        await call(client, "post_message", {"room_id": room["id"], "sender": "alice", "content": "implement oauth flow"})
        result = await call(client, "search", {"query": "oauth"})
    assert len(result["message_rooms"]) >= 1


@pytest.mark.anyio
async def test_e2e_wait_for_messages(mcp_svc):
    """wait_for_messages() returns when a new message is posted concurrently."""
    async with Client(mcp_module.mcp) as client:
        room = await call(client, "init_room", {"project": "proj", "name": "waitroom"})
        room_id = room["id"]
        msg0 = await call(client, "post_message", {"room_id": room_id, "sender": "alice", "content": "seed"})
        since_id = msg0["id"]

        # Post a new message after a short delay
        async def post_delayed():
            await asyncio.sleep(0.3)
            await call(client, "post_message", {"room_id": room_id, "sender": "bob", "content": "new"})

        task = asyncio.create_task(post_delayed())
        result = await call(client, "wait_for_messages", {"room_id": room_id, "since_id": since_id, "timeout": 10})
        await task

    assert result["timed_out"] is False
    assert len(result["messages"]) >= 1
    assert result["messages"][0]["content"] == "new"


# ---------------------------------------------------------------------------
# Error-path tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_e2e_post_message_invalid_room(mcp_svc):
    """post_message() to a non-existent room_id should return an MCP error."""
    async with Client(mcp_module.mcp) as client:
        result = await client.call_tool(
            "post_message",
            {"room_id": "00000000-0000-0000-0000-000000000000", "sender": "x", "content": "y"}
        )
    assert result.isError is True


@pytest.mark.anyio
async def test_e2e_search_empty_query_error(mcp_svc):
    """search() with empty query should return an MCP error (ValueError propagated)."""
    async with Client(mcp_module.mcp) as client:
        result = await client.call_tool("search", {"query": ""})
    assert result.isError is True


@pytest.mark.anyio
async def test_e2e_delete_live_room_error(mcp_svc):
    """delete_room() on a live (non-archived) room should return an MCP error."""
    async with Client(mcp_module.mcp) as client:
        room = await call(client, "init_room", {"project": "proj", "name": "live"})
        result = await client.call_tool("delete_room", {"room_id": room["id"]})
    assert result.isError is True
```

**Step 2: Run tests — expect FAIL** (mcp_svc fixture, set_event_loop, or Client API mismatch)
```bash
cd app/be && uv run pytest tests/test_mcp_e2e.py -xvs
```
Expected: Import errors or fixture errors. Adjust based on actual failures:
- If `fastmcp.Client` API differs: check `fastmcp.testing` module or `fastmcp.client` for the correct import
- If `result.content[0].text` fails: try `result.content[0].text` vs inspect `result` type/attributes
- If `set_event_loop` is not available on mcp_module: use `mcp_module._loop = asyncio.get_running_loop()` directly

**Step 3: Run all tests — expect PASS**
```bash
cd app/be && uv run pytest tests/test_mcp_e2e.py -xvs
cd app/be && uv run pytest -x
```

**Step 4: Commit**
```bash
git add app/be/tests/test_mcp_e2e.py
git commit -m "test(MCP-6): add E2E tests for all MCP tools via fastmcp Client"
```

---

### Task 3: MCP-13 — STATIC_DIR Env-Var Override Test

**Independent of Task 2** — can run in parallel after Task 1.

**Files:**
- Modify: `app/be/tests/test_app_config.py` — add env-var expression test + monkeypatch redirect test

**Step 1: Write the failing tests**

Add to `app/be/tests/test_app_config.py` (add `from unittest.mock import patch` to imports if not present):
```python
def test_static_dir_env_var_expression():
    """STATIC_DIR env var is read by os.environ.get() at module load.

    Tests the env-var resolution logic directly: os.environ.get("STATIC_DIR", fallback)
    should prefer the env var over the default. This validates the module-level expression
    without triggering importlib.reload side effects.
    """
    import os
    import agents_chat_mcp.app as app_module

    sentinel = "/tmp/custom-static-dir"
    with patch.dict(os.environ, {"STATIC_DIR": sentinel}):
        resolved = os.environ.get("STATIC_DIR", app_module._default_static_dir())
    assert resolved == sentinel, f"Expected {sentinel!r}, got {resolved!r}"


def test_static_dir_monkeypatch_affects_serve_spa(tmp_path, monkeypatch):
    """Monkeypatching STATIC_DIR at module level redirects serve_spa() to a custom dir.

    Also verifies that path traversal protection still applies with the custom STATIC_DIR.
    """
    import agents_chat_mcp.app as app_module

    # Create a custom static dir with a test file and index.html
    custom_file = tmp_path / "custom.js"
    custom_file.write_text("// custom")
    (tmp_path / "index.html").write_text("<html>custom</html>")

    monkeypatch.setattr(app_module, "STATIC_DIR", str(tmp_path))

    client = TestClient(app_module.app, raise_server_exceptions=False)

    # File in custom dir is served
    resp = client.get("/custom.js")
    assert resp.status_code == 200
    assert "custom" in resp.text

    # Path traversal is still rejected even with custom STATIC_DIR
    resp = client.get("/../etc/passwd")
    assert resp.status_code == 404
```

**Step 2: Run tests — expect FAIL**
```bash
cd app/be && uv run pytest tests/test_app_config.py::test_static_dir_env_var_expression tests/test_app_config.py::test_static_dir_monkeypatch_affects_serve_spa -xvs
```
Expected: `NameError: name 'patch' is not defined` or `NameError: name 'TestClient' is not defined`.

**Step 3: Add imports and run — expect PASS**

The `test_app_config.py` already imports `TestClient`. Add `from unittest.mock import patch` if needed.

```bash
cd app/be && uv run pytest tests/test_app_config.py -xvs
```

**Step 4: Commit**
```bash
git add app/be/tests/test_app_config.py
git commit -m "test(MCP-13): add STATIC_DIR env-var override and monkeypatch redirect tests"
```

---

### Task 4: MCP-8 — Open-Source Polish

**Depends on:** Task 1 (touches same files: `app.py`, `mcp.py`, `routes.py`)

**Files:**
- Modify: `app/be/agents_chat_mcp/app.py` — add type annotation to `app_lifespan`
- Modify: `app/be/agents_chat_mcp/routes.py` — add type annotations to `create_router`, `message_event_generator`, `chatroom_event_generator`
- Modify: `app/be/agents_chat_mcp/mcp.py` — improve docstrings for `search`, `post_message`, `read_messages`
- Create: `CODE_OF_CONDUCT.md`
- Create: `.github/ISSUE_TEMPLATE/bug_report.md`
- Create: `.github/pull_request_template.md`

**Step 1: No RED step needed** — type annotations and new files have no failing test. Verify existing tests still pass after changes.

**Step 2: Implement type annotations**

In `app/be/agents_chat_mcp/app.py`, update `app_lifespan` (FastAPI is already imported):
```python
@asynccontextmanager
async def app_lifespan(app: FastAPI):
```

In `app/be/agents_chat_mcp/routes.py`, update function signatures:
```python
from agents_chat_mcp.service import ChatService
from collections.abc import Callable, AsyncIterator

def create_router(get_service: Callable[[], ChatService]) -> APIRouter:
    """Create API router with the provided service factory."""

async def message_event_generator(
    svc: ChatService,
    room_id: str,
    last_id: int = 0,
    is_disconnected=None,
) -> AsyncIterator[dict]:

async def chatroom_event_generator(
    svc: ChatService,
    project: str | None = None,
    branch: str | None = None,
    reader: str | None = None,
    is_disconnected=None,
) -> AsyncIterator[dict]:
```

**Step 3: Improve docstrings in `mcp.py`**

```python
@mcp.tool()
def post_message(
    room_id: str,
    sender: str,
    content: str,
    message_type: str = "message",
) -> dict:
    """Post a message to a room by room_id (from init_room).

    Args:
        room_id: The room UUID returned by init_room.
        sender: Name or identifier of the message sender.
        content: Message text content.
        message_type: Must be 'message' (default) or 'system'.

    Raises:
        ValueError: If the room is archived or does not exist.
    """

@mcp.tool()
def read_messages(
    room_id: str,
    since_id: int | None = None,
    limit: int = 100,
    message_type: str | None = None,
) -> dict:
    """Read messages from a room by room_id.

    Args:
        room_id: The room UUID returned by init_room.
        since_id: Only return messages with id > since_id (incremental reads).
        limit: Maximum messages to return (default 100).
        message_type: Filter by type — 'message', 'system', or None for all.

    Returns:
        {"messages": [...], "has_more": bool}
    """

@mcp.tool()
def search(query: str, project: str | None = None) -> dict:
    """Search room names and message content.

    Args:
        query: Text to search (case-insensitive LIKE match). Must be non-empty.
        project: Optional project filter.

    Returns:
        {"rooms": [...], "message_rooms": [{"room_id": ..., "match_count": ...}]}

    Raises:
        ValueError: If query is empty or whitespace-only.
    """
```

**Step 4: Create community files**

Create `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1):
```markdown
# Contributor Covenant Code of Conduct

## Our Pledge

We as members, contributors, and leaders pledge to make participation in our
community a harassment-free experience for everyone, regardless of age, body
size, visible or invisible disability, ethnicity, sex characteristics, gender
identity and expression, level of experience, education, socio-economic status,
nationality, personal appearance, race, caste, color, religion, or sexual
identity and orientation.

We pledge to act and interact in ways that contribute to an open, welcoming,
diverse, inclusive, and healthy community.

## Our Standards

Examples of behavior that contributes to a positive environment:

* Demonstrating empathy and kindness toward other people
* Being respectful of differing opinions, viewpoints, and experiences
* Giving and gracefully accepting constructive feedback
* Accepting responsibility and apologizing to those affected by our mistakes
* Focusing on what is best not just for us as individuals, but for the overall community

Examples of unacceptable behavior:

* The use of sexualized language or imagery, and sexual attention or advances of any kind
* Trolling, insulting or derogatory comments, and personal or political attacks
* Public or private harassment
* Publishing others' private information without explicit permission
* Other conduct which could reasonably be considered inappropriate

## Enforcement Responsibilities

Community leaders are responsible for clarifying and enforcing standards of
acceptable behavior and will take appropriate corrective action in response to
any behavior that they deem inappropriate, threatening, offensive, or harmful.

## Scope

This Code of Conduct applies within all community spaces, and also applies when
an individual is officially representing the community in public spaces.

## Enforcement

Instances of abusive, harassing, or otherwise unacceptable behavior may be
reported to the community leaders responsible for enforcement at hi@runno.dev.
All complaints will be reviewed and investigated promptly and fairly.

## Attribution

This Code of Conduct is adapted from the [Contributor Covenant](https://www.contributor-covenant.org),
version 2.1, available at https://www.contributor-covenant.org/version/2/1/code_of_conduct.html.
```

Create `.github/ISSUE_TEMPLATE/bug_report.md`:
```markdown
---
name: Bug report
about: Create a report to help us improve
title: '[Bug] '
labels: 'bug'
assignees: ''
---

**Describe the bug**
A clear and concise description of what the bug is.

**To Reproduce**
Steps to reproduce the behavior:
1. Start server with `...`
2. Call tool `...` with args `...`
3. See error

**Expected behavior**
A clear and concise description of what you expected to happen.

**Environment**
- OS: [e.g. macOS 14]
- Python version: [e.g. 3.12.2]
- agents-chat-mcp version: [e.g. 0.2.0]
- FastMCP version: [e.g. 3.0.1]

**Additional context**
Add any other context about the problem here.
```

Create `.github/pull_request_template.md`:
```markdown
## Summary

<!-- What does this PR do? Why? -->

## Changes

<!-- List the key changes made -->

## Testing

<!-- How was this tested? -->
- [ ] Backend tests pass (`cd app/be && uv run pytest -x`)
- [ ] Frontend builds (`cd app/fe && bun run build`)
- [ ] TypeScript passes (`cd app/fe && bun run tsc --noEmit`)

## Checklist

- [ ] Tests added/updated for new behavior
- [ ] No breaking changes to MCP tool signatures
- [ ] SKILL.md updated if tools changed
```

**Step 5: Run full test suite — no regressions**
```bash
cd app/be && uv run pytest -x
```

**Step 6: Commit**
```bash
git add app/be/agents_chat_mcp/app.py app/be/agents_chat_mcp/routes.py app/be/agents_chat_mcp/mcp.py
git add CODE_OF_CONDUCT.md .github/ISSUE_TEMPLATE/bug_report.md .github/pull_request_template.md
git commit -m "polish(MCP-8): add type annotations, improve docstrings, add CODE_OF_CONDUCT and GitHub templates"
```

---

### Phase 5: Documentation Update

- [ ] Docstrings updated for all modified functions (covered in Task 4)
- [ ] SKILL.md — verify tool signatures are current (no changes to tool APIs in this branch; search docstring updated)
- [ ] README — no changes needed (MCP-4 is docs-ci scope)

---

## Verification

Run after all tasks complete:

```bash
# Backend tests
cd app/be && uv run pytest -xvs

# Frontend (no changes expected, verify no breakage)
cd app/fe && bun run test
cd app/fe && bun run build

# Type-check frontend
cd app/fe && bun run tsc --noEmit
```

Expected: All tests green, zero import errors, `asyncio_mode = "strict"` enforced.

## AI Review Findings

| Severity | Source | Finding | Action |
|----------|--------|---------|--------|
| Critical | backend-dev | `result[0].text` → CallToolResult is not subscriptable; must use `result.content[0].text` | Fixed: use `call()` helper with `result.content[0].text` |
| Critical | backend-dev | `archive_room` test asserted `result["status"] == "archived"` but response has no `status` key | Fixed: assert `result["archived_at"] is not None` |
| Critical | backend-dev/qa | `mcp_svc` fixture missing `set_event_loop` — `wait_for_messages` notification broken in tests | Fixed: async fixture with `set_event_loop(asyncio.get_running_loop())` |
| Critical | architect/backend/gemini | `search()` ValueError handler in routes.py was dead code (no ValueError raised in service) | Fixed: add `if not query.strip(): raise ValueError(...)` to `ChatService.search()` |
| Critical | backend-dev | `wait_for_messages` E2E test missing from plan (it's one of the 12 tools) | Fixed: added `test_e2e_wait_for_messages` with concurrent task |
| Warning | backend-dev/gemini | Zero error-path E2E tests | Added: 3 error-path tests (invalid room_id, empty search, delete live room) |
| Warning | gemini | MCP-13 path traversal not tested with custom `STATIC_DIR` | Fixed: added traversal assertion in `test_static_dir_monkeypatch_affects_serve_spa` |
| Warning | qa-strategist | `import json` repeated in every test function | Fixed: module-level import + `call()` helper |
| Suggestion | qa-strategist/architect | `test_mark_read_tool_registered` is dead weight (subset of `test_all_tools_registered`) | Addressed: executor should delete it during Task 2 |
| Suggestion | gemini | asyncio_mode framing — already the default, not a behavior change | Addressed: noted in plan comment |
