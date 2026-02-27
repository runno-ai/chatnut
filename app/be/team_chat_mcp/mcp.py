"""FastMCP tool definitions — thin wrappers over ChatService."""

import os
from typing import Callable

from fastmcp import FastMCP

from team_chat_mcp.service import ChatService

mcp = FastMCP("team-chat")

DB_PATH = os.path.expanduser(os.environ.get("CHAT_DB_PATH", "~/.claude/team-chat.db"))

_service_factory: Callable[[], ChatService] | None = None


def set_service_factory(factory: Callable[[], ChatService]) -> None:
    """Set the service factory used by all MCP tool handlers."""
    global _service_factory
    _service_factory = factory


def _get_service() -> ChatService:
    if _service_factory is None:
        raise RuntimeError("Service factory not set — call set_service_factory() before using MCP tools")
    return _service_factory()


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
    return _get_service().post_message_by_room_id(room_id, sender, content, message_type=message_type)


@mcp.tool()
def read_messages(
    room_id: str,
    since_id: int | None = None,
    limit: int = 100,
    message_type: str | None = None,
) -> dict:
    """Read messages from a room by room_id (from init_room). Use since_id for incremental polling. Default limit 100."""
    return _get_service().read_messages_by_room_id(room_id, since_id=since_id, limit=limit, message_type=message_type)


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
