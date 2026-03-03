# Auto-Update Notification System (MCP-12)

## Context

Users and agents have no way to know when a new chatnut version is available. This leads to running stale versions with missing features and bug fixes. MCP-12 adds three non-intrusive notification touch points: the `ping()` MCP tool, a web UI banner, and a startup log warning.

## Goal

Notify users and agents when a new chatnut version is available via GitHub releases API, with 1hr TTL in-memory cache and graceful degradation.

## Architecture

A new `version_check.py` module handles all version-related logic: fetching the latest release from GitHub API via `httpx.AsyncClient`, caching with 1hr TTL, and exposing both async `get_version_info()` and sync `get_cached_version_info()` functions. The module is initialized as a non-blocking background task on server startup. Three consumers read from the cached result via the sync accessor: `ping()` tool, `/api/status` REST endpoint, and startup log.

## Affected Areas

- Backend: `agents_chat_mcp/version_check.py` (new), `app.py`, `mcp.py`, `routes.py`, `pyproject.toml`
- Frontend: `hooks/useVersion.ts` (new), `components/UpdateBanner.tsx` (new), `App.tsx`, `types.ts`

## Key Files

- `app/be/agents_chat_mcp/version_check.py` — Core logic: GitHub API fetch, TTL cache, version comparison
- `app/be/agents_chat_mcp/app.py` — Startup background task, lifespan integration
- `app/be/agents_chat_mcp/mcp.py` — `ping()` tool extension
- `app/be/agents_chat_mcp/routes.py` — `/api/status` enrichment
- `app/fe/src/components/UpdateBanner.tsx` — Dismissible amber banner

## Reusable Utilities

- `app/be/agents_chat_mcp/app.py:app_lifespan` — Existing background task pattern (`_auto_archive_loop`)
- `app/fe/src/hooks/useProjects.ts` — One-shot fetch hook pattern to follow
- `app/fe/src/components/ConnectionStatus.tsx` — UI component placement pattern

---

## Tasks

### Task 1: Add httpx Runtime Dependency

**Files:**
- Modify: `app/be/pyproject.toml`

httpx is already a test dependency. Promote it to a runtime dependency for async GitHub API calls. This must happen before Task 2 which imports httpx.

**Step 1: Add httpx to runtime dependencies**

In `app/be/pyproject.toml`, add to the `[project] dependencies` array:

```toml
"httpx>=0.28",
```

**Step 2: Sync and verify**
```bash
cd app/be && uv sync --extra test && uv run python -c "import httpx; print(httpx.__version__)"
```

**Step 3: Commit**
```bash
git add app/be/pyproject.toml app/be/uv.lock
git commit -m "chore(mcp-12): promote httpx to runtime dependency"
```

---

### Task 2: Version Check Module

**Files:**
- Create: `app/be/agents_chat_mcp/version_check.py`
- Create: `app/be/tests/test_version_check.py`

**Step 1: Write the failing test**

```python
# tests/test_version_check.py
import json
import time
from unittest.mock import AsyncMock, patch, MagicMock

import httpx
import pytest

from agents_chat_mcp.version_check import (
    VersionInfo,
    get_current_version,
    fetch_latest_version,
    get_version_info,
    get_cached_version_info,
    _clear_cache,
    GITHUB_REPO,
    CACHE_TTL,
)


def test_version_info_update_available():
    info = VersionInfo(current="0.2.0", latest="0.3.0")
    assert info.update_available is True


def test_version_info_up_to_date():
    info = VersionInfo(current="0.3.0", latest="0.3.0")
    assert info.update_available is False


def test_version_info_no_latest():
    info = VersionInfo(current="0.3.0", latest=None)
    assert info.update_available is False


def test_version_info_to_dict_update():
    info = VersionInfo(current="0.2.0", latest="0.3.0")
    d = info.to_dict()
    assert d == {
        "version": "0.2.0",
        "latest": "0.3.0",
        "update_available": True,
    }


def test_version_info_to_dict_current():
    info = VersionInfo(current="0.3.0", latest="0.3.0")
    d = info.to_dict()
    assert d == {"version": "0.3.0"}


def test_version_info_to_dict_no_latest():
    info = VersionInfo(current="0.3.0", latest=None)
    d = info.to_dict()
    assert d == {"version": "0.3.0"}


def test_get_current_version():
    with patch("agents_chat_mcp.version_check.importlib.metadata.version", return_value="1.2.3"):
        v = get_current_version()
    assert v == "1.2.3"


def test_get_current_version_fallback():
    import importlib.metadata
    with patch(
        "agents_chat_mcp.version_check.importlib.metadata.version",
        side_effect=importlib.metadata.PackageNotFoundError("chatnut"),
    ):
        v = get_current_version()
    assert v == "0.0.0-dev"


def test_github_repo_constant():
    assert GITHUB_REPO == "runno-ai/chatnut"


def test_cache_ttl():
    assert CACHE_TTL == 3600


@pytest.mark.anyio
async def test_fetch_latest_version_success():
    mock_response = httpx.Response(
        200,
        json={"tag_name": "v0.5.0"},
        request=httpx.Request("GET", "https://example.com"),
    )
    with patch("agents_chat_mcp.version_check.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client
        result = await fetch_latest_version()
    assert result == "0.5.0"
    mock_client.get.assert_called_once()


@pytest.mark.anyio
async def test_fetch_latest_version_strips_v_prefix():
    mock_response = httpx.Response(
        200,
        json={"tag_name": "v1.2.3"},
        request=httpx.Request("GET", "https://example.com"),
    )
    with patch("agents_chat_mcp.version_check.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client
        result = await fetch_latest_version()
    assert result == "1.2.3"


@pytest.mark.anyio
async def test_fetch_latest_version_network_error():
    with patch("agents_chat_mcp.version_check.httpx.AsyncClient", side_effect=Exception("network")):
        result = await fetch_latest_version()
    assert result is None


@pytest.mark.anyio
async def test_fetch_latest_version_non_200():
    mock_response = httpx.Response(
        404,
        request=httpx.Request("GET", "https://example.com"),
    )
    with patch("agents_chat_mcp.version_check.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client
        result = await fetch_latest_version()
    assert result is None


@pytest.mark.anyio
async def test_get_version_info_caches():
    _clear_cache()
    with patch("agents_chat_mcp.version_check.get_current_version", return_value="0.1.0"):
        with patch(
            "agents_chat_mcp.version_check.fetch_latest_version",
            new_callable=AsyncMock,
            return_value="0.9.0",
        ) as mock_fetch:
            info1 = await get_version_info()
            info2 = await get_version_info()
            mock_fetch.assert_called_once()
    assert info1.latest == "0.9.0"
    assert info2.latest == "0.9.0"


@pytest.mark.anyio
async def test_get_version_info_returns_none_latest_on_failure():
    _clear_cache()
    with patch("agents_chat_mcp.version_check.get_current_version", return_value="0.1.0"):
        with patch(
            "agents_chat_mcp.version_check.fetch_latest_version",
            new_callable=AsyncMock,
            return_value=None,
        ):
            info = await get_version_info()
    assert info.latest is None
    assert info.update_available is False


def test_get_cached_version_info_empty_cache():
    _clear_cache()
    with patch("agents_chat_mcp.version_check.get_current_version", return_value="0.1.0"):
        info = get_cached_version_info()
    assert info.current == "0.1.0"
    assert info.latest is None
    assert info.update_available is False


@pytest.mark.anyio
async def test_get_cached_version_info_after_fetch():
    _clear_cache()
    with patch("agents_chat_mcp.version_check.get_current_version", return_value="0.1.0"):
        with patch(
            "agents_chat_mcp.version_check.fetch_latest_version",
            new_callable=AsyncMock,
            return_value="0.5.0",
        ):
            await get_version_info()  # populate cache
        info = get_cached_version_info()
    assert info.current == "0.1.0"
    assert info.latest == "0.5.0"
    assert info.update_available is True
```

**Step 2: Run test — expect FAIL**
```bash
cd app/be && uv run pytest tests/test_version_check.py -x --tb=short
```
Expected: `ModuleNotFoundError: No module named 'agents_chat_mcp.version_check'`

**Step 3: Implement minimal code**

```python
# agents_chat_mcp/version_check.py
"""Version checking via GitHub releases API with in-memory TTL cache."""

from __future__ import annotations

import importlib.metadata
import logging
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

GITHUB_REPO = "runno-ai/chatnut"
CACHE_TTL = 3600  # 1 hour


@dataclass
class VersionInfo:
    current: str
    latest: str | None

    @property
    def update_available(self) -> bool:
        # String equality is acceptable for this project's versioning scheme.
        # GitHub release tags and pyproject.toml versions are kept in lockstep
        # by the CD pipeline. For pre-release/post-release awareness, consider
        # packaging.version.Version in the future.
        return self.latest is not None and self.latest != self.current

    def to_dict(self) -> dict:
        d: dict = {"version": self.current}
        if self.update_available:
            d["latest"] = self.latest
            d["update_available"] = True
        return d


def get_current_version() -> str:
    try:
        return importlib.metadata.version("chatnut")
    except importlib.metadata.PackageNotFoundError:
        return "0.0.0-dev"


# --- Cache ---
# Thread safety note: _cache is a plain dict written from the async event loop
# (via get_version_info) and read from sync contexts (via get_cached_version_info).
# In CPython with the GIL, simple dict reads/writes are atomic. If free-threading
# (PEP 703) is adopted, this will need a lock.
_cache: dict[str, tuple[float, str | None]] = {}


def _clear_cache() -> None:
    _cache.clear()


async def fetch_latest_version() -> str | None:
    """Fetch latest release tag from GitHub. Returns None on any failure."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": f"chatnut/{get_current_version()}",
                },
                timeout=10.0,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            tag = data.get("tag_name", "")
            return tag.lstrip("v") if tag else None
    except Exception:
        return None


async def get_version_info() -> VersionInfo:
    """Get version info, fetching from GitHub if cache is expired."""
    current = get_current_version()
    cached = _cache.get("latest")
    if cached is not None:
        ts, version = cached
        if time.monotonic() - ts < CACHE_TTL:
            return VersionInfo(current=current, latest=version)

    latest = await fetch_latest_version()
    _cache["latest"] = (time.monotonic(), latest)
    return VersionInfo(current=current, latest=latest)


def get_cached_version_info() -> VersionInfo:
    """Read version info from cache only (sync-safe, no network I/O).
    Returns VersionInfo with latest=None if cache is empty or expired."""
    current = get_current_version()
    cached = _cache.get("latest")
    if cached is not None:
        ts, version = cached
        if time.monotonic() - ts < CACHE_TTL:
            return VersionInfo(current=current, latest=version)
    return VersionInfo(current=current, latest=None)
```

**Step 4: Run test — expect PASS**
```bash
cd app/be && uv run pytest tests/test_version_check.py -x --tb=short
```

**Step 5: Commit**
```bash
git add app/be/agents_chat_mcp/version_check.py app/be/tests/test_version_check.py
git commit -m "feat(mcp-12): add version_check module with GitHub API + TTL cache"
```

---

### Task 3: Startup Background Check + Log Warning

**Files:**
- Modify: `app/be/agents_chat_mcp/app.py`
- Create: `app/be/tests/test_app_startup.py`

**Step 1: Write the failing test**

```python
# tests/test_app_startup.py
import logging
from unittest.mock import AsyncMock, patch

import pytest

from agents_chat_mcp.version_check import VersionInfo


@pytest.mark.anyio
async def test_startup_logs_update_warning(caplog):
    """Startup should log a warning when an update is available."""
    mock_info = VersionInfo(current="0.2.0", latest="0.3.0")
    with patch(
        "agents_chat_mcp.app.get_version_info",
        new_callable=AsyncMock,
        return_value=mock_info,
    ):
        from agents_chat_mcp.app import _check_version_on_startup

        with caplog.at_level(logging.WARNING, logger="agents_chat_mcp.app"):
            await _check_version_on_startup()

    assert any("0.3.0" in r.message and "update" in r.message.lower() for r in caplog.records)


@pytest.mark.anyio
async def test_startup_no_warning_when_current(caplog):
    """No warning logged when already on latest version."""
    mock_info = VersionInfo(current="0.3.0", latest="0.3.0")
    with patch(
        "agents_chat_mcp.app.get_version_info",
        new_callable=AsyncMock,
        return_value=mock_info,
    ):
        from agents_chat_mcp.app import _check_version_on_startup

        with caplog.at_level(logging.WARNING, logger="agents_chat_mcp.app"):
            await _check_version_on_startup()

    assert not any("update" in r.message.lower() for r in caplog.records)


@pytest.mark.anyio
async def test_startup_silent_on_failure(caplog):
    """No warning or error when GitHub API fails."""
    mock_info = VersionInfo(current="0.3.0", latest=None)
    with patch(
        "agents_chat_mcp.app.get_version_info",
        new_callable=AsyncMock,
        return_value=mock_info,
    ):
        from agents_chat_mcp.app import _check_version_on_startup

        with caplog.at_level(logging.WARNING, logger="agents_chat_mcp.app"):
            await _check_version_on_startup()

    assert not any("update" in r.message.lower() for r in caplog.records)
```

**Step 2: Run test — expect FAIL**
```bash
cd app/be && uv run pytest tests/test_app_startup.py -x --tb=short
```
Expected: `ImportError: cannot import name '_check_version_on_startup'`

**Step 3: Implement minimal code**

Add to `app/be/agents_chat_mcp/app.py`:

```python
# At top — add import
from agents_chat_mcp.version_check import get_version_info

# New function (add before app_lifespan)
async def _check_version_on_startup() -> None:
    """Background version check — logs warning if update available."""
    try:
        info = await get_version_info()
        if info.update_available:
            logger.warning(
                "chatnut %s available (you have %s). "
                "Run: uv tool upgrade chatnut",
                info.latest,
                info.current,
            )
    except Exception:
        pass  # Graceful degradation — never fail startup
```

Modify `app_lifespan` to add the version check task (stored + cancelled on shutdown):

```python
@asynccontextmanager
async def app_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    _get_service()
    mcp_module.set_event_loop(asyncio.get_running_loop())
    archive_task = asyncio.create_task(_auto_archive_loop())
    version_task = asyncio.create_task(_check_version_on_startup())
    yield
    version_task.cancel()
    archive_task.cancel()
    try:
        await archive_task
    except asyncio.CancelledError:
        pass
    try:
        await version_task
    except asyncio.CancelledError:
        pass
    mcp_module.set_event_loop(None)
```

**Step 4: Run test — expect PASS**
```bash
cd app/be && uv run pytest tests/test_app_startup.py -x --tb=short
```

**Step 5: Commit**
```bash
git add app/be/agents_chat_mcp/app.py app/be/tests/test_app_startup.py
git commit -m "feat(mcp-12): add startup version check with log warning"
```

---

### Task 4: Extend ping() Tool

**Files:**
- Modify: `app/be/agents_chat_mcp/mcp.py`
- Modify: `app/be/tests/test_mcp.py`
- Modify: `app/be/tests/test_mcp_e2e.py`

**Step 1: Write the failing test**

Add to `tests/test_mcp.py`:

```python
def test_ping_includes_version(db):
    from unittest.mock import patch
    from agents_chat_mcp import mcp as mcp_module
    from agents_chat_mcp.version_check import VersionInfo

    svc = ChatService(db)
    original = mcp_module._service_factory
    mcp_module.set_service_factory(lambda: svc)
    try:
        with patch(
            "agents_chat_mcp.mcp.get_cached_version_info",
            return_value=VersionInfo(current="0.2.0", latest="0.3.0"),
        ):
            result = mcp_module.ping()
        assert result["version"] == "0.2.0"
        assert result["latest"] == "0.3.0"
        assert result["update_available"] is True
    finally:
        mcp_module.set_service_factory(original)


def test_ping_version_no_update(db):
    from unittest.mock import patch
    from agents_chat_mcp import mcp as mcp_module
    from agents_chat_mcp.version_check import VersionInfo

    svc = ChatService(db)
    original = mcp_module._service_factory
    mcp_module.set_service_factory(lambda: svc)
    try:
        with patch(
            "agents_chat_mcp.mcp.get_cached_version_info",
            return_value=VersionInfo(current="0.3.0", latest="0.3.0"),
        ):
            result = mcp_module.ping()
        assert result["version"] == "0.3.0"
        assert "latest" not in result
        assert "update_available" not in result
    finally:
        mcp_module.set_service_factory(original)
```

Add to `tests/test_mcp_e2e.py`:

```python
@pytest.mark.anyio
async def test_e2e_ping_includes_version(mcp_svc):
    from unittest.mock import patch
    from agents_chat_mcp.version_check import VersionInfo

    with patch(
        "agents_chat_mcp.mcp.get_cached_version_info",
        return_value=VersionInfo(current="0.1.0", latest=None),
    ):
        async with Client(mcp_module.mcp) as client:
            data = await call(client, "ping")
    assert data["status"] == "ok"
    assert "version" in data
```

**Step 2: Run test — expect FAIL**
```bash
cd app/be && uv run pytest tests/test_mcp.py::test_ping_includes_version tests/test_mcp_e2e.py::test_e2e_ping_includes_version -x --tb=short
```
Expected: `AssertionError` or `ImportError`

**Step 3: Implement minimal code**

Modify `ping()` in `mcp.py`:

```python
# At top of mcp.py — add import
from agents_chat_mcp.version_check import get_cached_version_info

@mcp.tool()
def ping() -> dict:
    """Health check — returns the database file path, status, and version info."""
    result = {"db_path": _get_service().db_path(), "status": "ok"}
    result.update(get_cached_version_info().to_dict())
    return result
```

**Step 4: Run test — expect PASS**
```bash
cd app/be && uv run pytest tests/test_mcp.py::test_ping_includes_version tests/test_mcp.py::test_ping_version_no_update tests/test_mcp_e2e.py::test_e2e_ping_includes_version -x --tb=short
```

**Step 5: Commit**
```bash
git add app/be/agents_chat_mcp/mcp.py app/be/tests/test_mcp.py app/be/tests/test_mcp_e2e.py
git commit -m "feat(mcp-12): extend ping() with version info via get_cached_version_info()"
```

---

### Task 5: Extend /api/status REST Endpoint

**Files:**
- Modify: `app/be/agents_chat_mcp/routes.py`
- Modify: `app/be/tests/test_routes.py`

**Step 1: Write the failing test**

Add to `tests/test_routes.py`:

```python
def test_status_includes_version(client):
    from unittest.mock import patch
    from agents_chat_mcp.version_check import VersionInfo

    with patch(
        "agents_chat_mcp.routes.get_cached_version_info",
        return_value=VersionInfo(current="0.2.0", latest="0.3.0"),
    ):
        resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["version"] == "0.2.0"
    assert data["latest"] == "0.3.0"
    assert data["update_available"] is True


def test_status_no_update(client):
    from unittest.mock import patch
    from agents_chat_mcp.version_check import VersionInfo

    with patch(
        "agents_chat_mcp.routes.get_cached_version_info",
        return_value=VersionInfo(current="0.3.0", latest="0.3.0"),
    ):
        resp = client.get("/api/status")
    data = resp.json()
    assert data["version"] == "0.3.0"
    assert "latest" not in data
```

**Step 2: Run test — expect FAIL**
```bash
cd app/be && uv run pytest tests/test_routes.py::test_status_includes_version -x --tb=short
```
Expected: `AssertionError: 'version' not in {'status': 'ok'}`

**Step 3: Implement minimal code**

Modify `/api/status` in `routes.py`:

```python
# At top of routes.py — add import
from agents_chat_mcp.version_check import get_cached_version_info

@router.get("/status")
def status():
    result = {"status": "ok"}
    result.update(get_cached_version_info().to_dict())
    return result
```

**Step 4: Run test — expect PASS**
```bash
cd app/be && uv run pytest tests/test_routes.py::test_status_includes_version tests/test_routes.py::test_status_no_update -x --tb=short
```

**Step 5: Commit**
```bash
git add app/be/agents_chat_mcp/routes.py app/be/tests/test_routes.py
git commit -m "feat(mcp-12): extend /api/status with version info"
```

---

### Task 6: Frontend Update Banner

**Files:**
- Create: `app/fe/src/hooks/useVersion.ts`
- Create: `app/fe/src/hooks/__tests__/useVersion.test.ts`
- Create: `app/fe/src/components/UpdateBanner.tsx`
- Modify: `app/fe/src/App.tsx`
- Modify: `app/fe/src/types.ts`

**Step 1: Write the failing test**

```typescript
// app/fe/src/hooks/__tests__/useVersion.test.ts
import { renderHook, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { useVersion } from "../useVersion";

describe("useVersion", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("fetches version info from /api/status", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        status: "ok",
        version: "0.2.0",
        latest: "0.3.0",
        update_available: true,
      }),
    } as Response);

    const { result } = renderHook(() => useVersion());
    await waitFor(() => expect(result.current).not.toBeNull());
    expect(result.current?.version).toBe("0.2.0");
    expect(result.current?.latest).toBe("0.3.0");
    expect(result.current?.update_available).toBe(true);
  });

  it("returns null on fetch failure", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new Error("network"));
    const { result } = renderHook(() => useVersion());
    // Verify state stays null after the fetch cycle completes
    await waitFor(
      () => {
        expect(result.current).toBeNull();
      },
      { timeout: 200 },
    );
  });
});
```

**Step 2: Run test — expect FAIL**
```bash
cd app/fe && bun run test -- src/hooks/__tests__/useVersion.test.ts
```
Expected: `Cannot find module '../useVersion'`

**Step 3: Implement minimal code**

```typescript
// app/fe/src/types.ts — add interface at end
export interface VersionStatus {
  version: string;
  latest?: string;
  update_available?: boolean;
}
```

```typescript
// app/fe/src/hooks/useVersion.ts
import { useState, useEffect } from "react";
import type { VersionStatus } from "../types";

export function useVersion(): VersionStatus | null {
  const [info, setInfo] = useState<VersionStatus | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/status", { signal: controller.signal })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => setInfo(data))
      .catch(() => {});
    return () => controller.abort();
  }, []);

  return info;
}
```

```tsx
// app/fe/src/components/UpdateBanner.tsx
import { useState } from "react";
import type { VersionStatus } from "../types";

export function UpdateBanner({ info }: { info: VersionStatus }) {
  const [dismissed, setDismissed] = useState(false);

  if (!info.update_available || dismissed) return null;

  return (
    <div
      className="bg-amber-500/15 border-b border-amber-500/30 px-4 py-2 text-sm text-amber-200 flex items-center justify-between"
      role="status"
    >
      <span>
        v{info.latest} available — run{" "}
        <code className="bg-amber-500/20 px-1.5 py-0.5 rounded text-xs">
          uv tool upgrade chatnut
        </code>{" "}
        to update
      </span>
      <button
        onClick={() => setDismissed(true)}
        className="text-amber-400 hover:text-amber-200 ml-4 text-lg leading-none"
        aria-label="Dismiss update notification"
      >
        {"\u00d7"}
      </button>
    </div>
  );
}
```

Modify `App.tsx` — wrap root in flex-col to place banner above the sidebar/chat row:

```tsx
// app/fe/src/App.tsx — add imports
import { useVersion } from "./hooks/useVersion";
import { UpdateBanner } from "./components/UpdateBanner";

// Inside App component body:
const versionInfo = useVersion();

// Wrap JSX root in flex-col:
return (
  <div className="flex flex-col h-screen bg-gray-950 text-gray-100 overflow-hidden">
    {versionInfo?.update_available && <UpdateBanner info={versionInfo} />}
    <div className="flex flex-1 overflow-hidden">
      {/* existing Sidebar + ChatView layout (move current flex children here) */}
    </div>
  </div>
);
```

**Step 4: Run test — expect PASS**
```bash
cd app/fe && bun run test -- src/hooks/__tests__/useVersion.test.ts
```

**Step 5: Commit**
```bash
git add app/fe/src/types.ts app/fe/src/hooks/useVersion.ts app/fe/src/hooks/__tests__/useVersion.test.ts app/fe/src/components/UpdateBanner.tsx app/fe/src/App.tsx
git commit -m "feat(mcp-12): add update banner in web UI with flex-col layout"
```

---

### Task 7: Documentation Update

- [ ] Update `CLAUDE.md` — add `version_check.py` to project structure, note update notification in Design Decisions, update ping() tool signature in Tools table
- [ ] Update `SKILL.md` — update ping() tool signature to include `version`, `latest`, `update_available` fields

---

## Verification

```bash
# Backend: all tests pass
cd app/be && uv run pytest -xvs

# Frontend: typecheck + tests + build
cd app/fe && bunx tsc --noEmit && bun run test && bun run build
```

Expected: All tests pass, no type errors, build succeeds.

## AI Review Findings

| Severity | Source | Finding | Action |
|----------|--------|---------|--------|
| Critical | ALL | Task ordering: dependency must come before module | Moved httpx to Task 1 |
| Critical | 4/5 | `_cache` imported directly by consumers | Added `get_cached_version_info()` sync accessor |
| Critical | 3/5 | Banner placement breaks flex layout | Wrapped root in flex-col |
| Warning | 4/5 | aiohttp is heavy; httpx already in deps | Switched to httpx |
| Warning | Gemini | Missing User-Agent header for GitHub API | Added header |
| Warning | 3/5 | Fire-and-forget task not cancelled on shutdown | Stored + cancelled |
| Warning | 2/5 | Cache test doesn't assert call count | Added assert_called_once() |
| Warning | 2/5 | Flaky setTimeout in frontend test | Replaced with waitFor |
| Warning | FE | Dismiss button uses literal "x" | Changed to × (U+00D7) |
| Suggestion | FE | Add role="status" for accessibility | Added |
| Suggestion | 3/5 | Semver comparison vs string equality | Accepted for v1, documented in comment |
| Suggestion | Codex | PackageNotFoundError fallback | Added 0.0.0-dev fallback |
| Suggestion | Gemini | Frontend periodic re-check | Deferred to future enhancement |
| Note | ALL | Package name IS `chatnut` (repo renamed on main) | Confirmed by user; false positive dismissed |
