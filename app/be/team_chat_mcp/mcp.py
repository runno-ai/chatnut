"""FastMCP tool definitions — thin wrappers over ChatService."""

import asyncio
import os
from collections import defaultdict
from typing import Callable

import anyio
from fastmcp import FastMCP

from team_chat_mcp.service import ChatService

mcp = FastMCP("team-chat")

DB_PATH = os.path.expanduser(os.environ.get("CHAT_DB_PATH", "~/.claude/team-chat.db"))

_service_factory: Callable[[], ChatService] | None = None

# Waiter registry: room_id → set of asyncio.Queue objects
# All mutations happen exclusively on the event loop thread (via _wake_all callback).
_waiters: defaultdict[str, set[asyncio.Queue[None]]] = defaultdict(set)

# Running event loop — set from app_lifespan for thread-safe notification
_loop: asyncio.AbstractEventLoop | None = None

# Maximum concurrent waiters per room — prevents DoS via connection flooding
MAX_WAITERS_PER_ROOM = 100


def set_service_factory(factory: Callable[[], ChatService]) -> None:
    """Set the service factory used by all MCP tool handlers."""
    global _service_factory
    _service_factory = factory


def set_event_loop(loop: asyncio.AbstractEventLoop | None) -> None:
    """Store the running event loop for cross-thread waiter notification."""
    global _loop
    _loop = loop


def _get_service() -> ChatService:
    if _service_factory is None:
        raise RuntimeError("Service factory not set — call set_service_factory() before using MCP tools")
    return _service_factory()


def _notify_waiters(room_id: str) -> None:
    """Wake up all wait_for_messages callers blocked on room_id.

    Thread-safe: schedules _wake_all onto the event loop via call_soon_threadsafe so
    _waiters is only ever touched on the event loop thread.

    Safe to call on a closed or missing loop — both cases are no-ops.

    IMPORTANT: Do NOT call from a finally block — must only fire on successful inserts.
    """
    if _loop is None or _loop.is_closed():
        return

    def _wake_all() -> None:
        # Runs on the event loop thread — safe to read/iterate _waiters here
        for q in list(_waiters.get(room_id, ())):
            q.put_nowait(None)

    try:
        _loop.call_soon_threadsafe(_wake_all)
    except RuntimeError:
        pass  # loop closed between is_closed() check and call_soon_threadsafe


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
    room_id: str,
    sender: str,
    content: str,
    message_type: str = "message",
) -> dict:
    """Post a message to a room by room_id (from init_room). Rejects posts to archived rooms."""
    result = _get_service().post_message_by_room_id(room_id, sender, content, message_type=message_type)
    _notify_waiters(room_id)  # only reached on successful insert
    return result


@mcp.tool()
def read_messages(
    room_id: str,
    since_id: int | None = None,
    limit: int = 100,
    message_type: str | None = None,
) -> dict:
    """Read messages from a room by room_id. Use since_id for incremental reads. Default limit 100."""
    return _get_service().read_messages_by_room_id(room_id, since_id=since_id, limit=limit, message_type=message_type)


@mcp.tool()
async def wait_for_messages(
    room_id: str,
    since_id: int,
    timeout: float = 30.0,
    limit: int = 100,
    message_type: str | None = None,
) -> dict:
    """Block until new messages arrive in room_id after since_id, or timeout seconds.

    Raises ValueError for unknown room_id or negative since_id (fail fast — don't silently
    hang 30s on a typo). Timeout is capped at 60s to prevent holding connections indefinitely.

    The queue is registered BEFORE the early-exit DB check — TOCTOU-safe: any message posted
    after registration fires _notify_waiters which puts an item in the queue, so it's picked
    up either by the early-exit check or by await q.get(), with no gap.

    Returns:
        messages: list of new messages (may be empty if woken then no new msg at since_id)
        has_more: whether more messages exist beyond limit
        timed_out: True if no message arrived within timeout; False otherwise
    """
    if since_id < 0:
        raise ValueError(f"since_id must be >= 0, got {since_id}")
    if timeout < 0:
        raise ValueError(f"timeout must be >= 0, got {timeout}")

    exists = await anyio.to_thread.run_sync(lambda: _get_service().room_exists(room_id))
    if not exists:
        raise ValueError(f"Room '{room_id}' not found")

    timeout = min(timeout, 60.0)

    q: asyncio.Queue[None] = asyncio.Queue()
    # Enforce per-room waiter limit to prevent DoS via connection flooding
    if len(_waiters[room_id]) >= MAX_WAITERS_PER_ROOM:
        raise ValueError(f"Too many concurrent waiters for room '{room_id}' (max {MAX_WAITERS_PER_ROOM})")
    # Register BEFORE the DB check — see TOCTOU note in docstring
    _waiters[room_id].add(q)
    try:
        # Early exit: return immediately if messages already exist after since_id
        existing = await anyio.to_thread.run_sync(
            lambda: _get_service().read_messages_by_room_id(
                room_id, since_id=since_id, limit=limit, message_type=message_type
            )
        )
        if existing["messages"]:
            existing["timed_out"] = False
            return existing

        # Block until _notify_waiters fires _wake_all or timeout elapses
        woken = False
        with anyio.move_on_after(timeout):
            await q.get()
            woken = True

        if not woken:
            # Final re-check: a message may have been posted concurrently with the timeout.
            # This closes the race between anyio's deadline firing and a pending _notify_waiters call,
            # and also handles the case where _loop was None so notifications were not delivered.
            final = await anyio.to_thread.run_sync(
                lambda: _get_service().read_messages_by_room_id(
                    room_id, since_id=since_id, limit=limit, message_type=message_type
                )
            )
            if final["messages"]:
                final["timed_out"] = False
                return final
            return {"messages": [], "has_more": False, "timed_out": True}

        result = await anyio.to_thread.run_sync(
            lambda: _get_service().read_messages_by_room_id(
                room_id, since_id=since_id, limit=limit, message_type=message_type
            )
        )
        result["timed_out"] = False
        return result
    finally:
        _waiters[room_id].discard(q)
        # Clean up empty sets to avoid unbounded memory growth in long-running server
        if not _waiters[room_id]:
            _waiters.pop(room_id, None)


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
def delete_room(room_id: str) -> dict:
    """Permanently delete a room and all its messages. Only archived rooms can be deleted."""
    return _get_service().delete_room(room_id)


@mcp.tool()
def clear_room(project: str, name: str) -> dict:
    """Delete all messages in a room. Keeps the room record."""
    return _get_service().clear_room(project, name)


@mcp.tool()
def search(query: str, project: str | None = None) -> dict:
    """Search room names and message content. Optionally filter by project."""
    return _get_service().search(query, project=project)


@mcp.tool()
def mark_read(
    room_id: str,
    reader: str,
    last_read_message_id: int,
) -> dict:
    """Mark messages as read up to the given message ID for a reader. Cursor only moves forward."""
    return _get_service().mark_read(room_id, reader, last_read_message_id)
