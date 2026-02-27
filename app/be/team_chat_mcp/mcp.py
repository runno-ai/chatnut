"""FastMCP tool definitions — thin wrappers over ChatService."""

import os
from functools import lru_cache

from fastmcp import FastMCP

from team_chat_mcp.db import init_db
from team_chat_mcp.service import ChatService

mcp = FastMCP("team-chat")

DB_PATH = os.path.expanduser(os.environ.get("CHAT_DB_PATH", "~/.claude/team-chat.db"))


@lru_cache(maxsize=1)
def _get_service() -> ChatService:
    db_conn = init_db(DB_PATH)
    return ChatService(db_conn)


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
    project: str,
    room: str,
    sender: str,
    content: str,
    message_type: str = "message",
) -> dict:
    """Post a message to a room. Auto-creates room if missing. Rejects posts to archived rooms."""
    return _get_service().post_message(project, room, sender, content, message_type=message_type)


@mcp.tool()
def read_messages(
    project: str,
    room: str,
    since_id: int | None = None,
    limit: int = 100,
    message_type: str | None = None,
) -> dict:
    """Read messages from a room. Use since_id for incremental polling. Default limit 100."""
    return _get_service().read_messages(project, room, since_id=since_id, limit=limit, message_type=message_type)


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
def clear_room(project: str, name: str) -> dict:
    """Delete all messages in a room. Keeps the room record."""
    return _get_service().clear_room(project, name)


@mcp.tool()
def search(query: str, project: str | None = None) -> dict:
    """Search room names and message content. Optionally filter by project."""
    return _get_service().search(query, project=project)
