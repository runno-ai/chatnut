"""FastMCP tool definitions — thin wrappers over ChatService."""

import asyncio
import json
import logging
import os
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

import anyio
from fastmcp import FastMCP

from chatnut.service import ChatService
from chatnut.version_check import get_cached_version_info

logger = logging.getLogger(__name__)

mcp = FastMCP("agents-chat")

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


def _get_web_base_url() -> str | None:
    """Read server port file and return base URL, or None if unavailable."""
    run_dir = Path(os.environ.get("CHATNUT_RUN_DIR", Path.home() / ".chatnut"))
    port_file = run_dir / "server.port"
    if not port_file.exists():
        return None
    try:
        port = int(port_file.read_text().strip())
        return f"http://127.0.0.1:{port}"
    except (ValueError, OSError):
        return None


def _write_team_chatroom(team_name: str, room_data: dict) -> None:
    """Write chatroom.json to the team config directory.

    Sanitizes team_name with os.path.basename() to prevent path traversal.
    Silently returns if the team directory does not exist.
    File write failures are logged as warnings and are non-fatal.

    Args:
        team_name: The team name (directory under CLAUDE_TEAMS_DIR).
        room_data: The room dict returned by init_room (may include web_url).
    """
    # Sanitize to prevent path traversal (e.g. "../../etc")
    safe_name = os.path.basename(team_name)
    if not safe_name or safe_name != team_name:
        logger.warning(
            "init_room: team_name %r rejected (path traversal attempt or empty after sanitization)",
            team_name,
        )
        return

    teams_dir = Path(os.environ.get("CLAUDE_TEAMS_DIR", Path.home() / ".claude" / "teams"))
    team_dir = teams_dir / safe_name

    if not team_dir.exists():
        return

    chatroom_data: dict = {
        "room_id": room_data.get("id"),
        "project": room_data.get("project"),
        "name": room_data.get("name"),
    }
    if "web_url" in room_data:
        chatroom_data["web_url"] = room_data["web_url"]

    try:
        (team_dir / "chatroom.json").write_text(json.dumps(chatroom_data, indent=2))
    except OSError as exc:
        logger.warning("init_room: failed to write chatroom.json for team %r: %s", team_name, exc)


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
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                pass  # already signaled; one pending notification is sufficient

    try:
        _loop.call_soon_threadsafe(_wake_all)
    except RuntimeError:
        pass  # loop closed between is_closed() check and call_soon_threadsafe


@mcp.tool()
def ping() -> dict:
    """Health check — returns the database file path, status, and version info."""
    result = {"db_path": _get_service().db_path(), "status": "ok"}
    result.update(get_cached_version_info().to_dict())
    web_url = _get_web_base_url()
    if web_url:
        result["web_url"] = web_url
    return result


@mcp.tool()
def init_room(
    project: str,
    name: str,
    branch: str | None = None,
    description: str | None = None,
    team_name: str | None = None,
) -> dict:
    """Create a new chatroom. Idempotent — returns existing room if already created.

    Automatically opens the chatroom in the user's browser when the server is running.
    The response includes a `web_url` field with the direct link.
    Set CHATNUT_OPEN_BROWSER=0 to suppress auto-open (e.g. in CI/tests).

    When team_name is provided, writes chatroom.json to the team config directory
    (~/.claude/teams/<team_name>/chatroom.json or CLAUDE_TEAMS_DIR/<team_name>/chatroom.json).
    Non-fatal: file write failures are logged as warnings.
    """
    result = _get_service().init_room(project, name, branch=branch, description=description)
    web_url = _get_web_base_url()
    if web_url:
        room_url = f"{web_url}/?room={result['id']}"
        result["web_url"] = room_url
        if os.environ.get("CHATNUT_OPEN_BROWSER", "1") != "0":
            import webbrowser
            webbrowser.open(room_url)
    if team_name is not None:
        _write_team_chatroom(team_name, result)
    return result


@mcp.tool()
def post_message(
    room_id: str,
    sender: str,
    content: str,
    message_type: str = "message",
) -> dict:
    """Post a message to a room by room_id (from init_room). Rejects posts to archived rooms.

    Args:
        room_id: The room UUID returned by init_room.
        sender: Name or identifier of the message sender.
        content: Message text content.
        message_type: Must be 'message' (default) or 'system'.

    Raises:
        ValueError: If the room is archived or does not exist.
    """
    svc = _get_service()
    with svc.lock:
        result = svc.post_message_by_room_id(room_id, sender, content, message_type=message_type)
    _notify_waiters(room_id)  # only reached on successful insert
    return result


@mcp.tool()
def read_messages(
    room_id: str,
    since_id: int | None = None,
    limit: int = 100,
    message_type: str | None = None,
) -> dict:
    """Read messages from a room by room_id. Use since_id for incremental reads. Default limit 100.

    Args:
        room_id: The room UUID returned by init_room.
        since_id: Only return messages with id > since_id (incremental reads).
        limit: Maximum messages to return (default 100).
        message_type: Filter by type — 'message', 'system', or None for all.

    Returns:
        {"messages": [...], "has_more": bool}
    """
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

    # maxsize=1: signal queue — one pending notification is sufficient; extras are coalesced
    q: asyncio.Queue[None] = asyncio.Queue(maxsize=1)
    # Enforce per-room waiter limit to prevent DoS via connection flooding
    if len(_waiters[room_id]) >= MAX_WAITERS_PER_ROOM:
        raise ValueError(f"Too many concurrent waiters for room '{room_id}' (max {MAX_WAITERS_PER_ROOM})")
    # Register BEFORE the DB check — see TOCTOU note in docstring
    _waiters[room_id].add(q)
    try:
        # Early exit: return immediately if messages already exist after since_id
        svc = _get_service()

        def _read():
            with svc.lock:
                return svc.read_messages_by_room_id(
                    room_id, since_id=since_id, limit=limit, message_type=message_type
                )

        existing = await anyio.to_thread.run_sync(_read)
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
            final = await anyio.to_thread.run_sync(_read)
            if final["messages"]:
                final["timed_out"] = False
                return final
            return {"messages": [], "has_more": False, "timed_out": True}

        result = await anyio.to_thread.run_sync(_read)
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
    """Search room names and message content. Optionally filter by project.

    Args:
        query: Text to search (case-insensitive LIKE match). Must be non-empty.
        project: Optional project filter.

    Returns:
        {"rooms": [...], "message_rooms": [{"room_id": ..., "match_count": ...}]}

    Raises:
        ValueError: If query is empty or whitespace-only.
    """
    return _get_service().search(query, project=project)


@mcp.tool()
def mark_read(
    room_id: str,
    reader: str,
    last_read_message_id: int,
) -> dict:
    """Mark messages as read up to the given message ID for a reader. Cursor only moves forward."""
    return _get_service().mark_read(room_id, reader, last_read_message_id)


@mcp.tool()
def update_status(room_id: str, sender: str, status: str) -> dict:
    """Set or update a sender's status in a room.

    Args:
        room_id: The room UUID returned by init_room.
        sender: Name or identifier of the agent updating their status.
        status: Status string (e.g. 'idle', 'working', 'done').

    Raises:
        ValueError: If the room does not exist or is archived.
    """
    return _get_service().update_status(room_id, sender, status)


@mcp.tool()
def get_team_status(room_id: str) -> dict:
    """Get all current statuses for all senders in a room.

    Args:
        room_id: The room UUID returned by init_room.

    Returns:
        {"statuses": [...]} — list of {room_id, sender, status, updated_at} dicts.

    Raises:
        ValueError: If the room does not exist.
    """
    return _get_service().get_team_status(room_id)


@mcp.tool()
def register_agent(room_id: str, agent_name: str, task_id: str) -> dict:
    """Register an agent in a room for @mention notifications.

    When a message containing @<agent_name> is posted to this room,
    post_message will include the agent's task_id in its response,
    enabling the caller to SendMessage the mentioned agent.

    UPSERT semantics — re-registering with a different task_id replaces the old one.
    agent_name is normalized to lowercase for case-insensitive matching.

    Args:
        room_id: The room UUID returned by init_room.
        agent_name: Mention name used in @mentions after strip/lower normalization.
            Must contain only letters, numbers, underscores, or hyphens.
        task_id: Non-empty CC agent/task name to SendMessage to when @mentioned.

    Raises:
        ValueError: If agent_name/task_id is invalid, or if the room does not exist or is archived.
    """
    svc = _get_service()
    with svc.lock:
        return svc.register_agent(room_id, agent_name, task_id)


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
