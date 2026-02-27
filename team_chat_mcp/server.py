"""Team Chat MCP Server — thin tool wrappers over ChatService."""

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
def init_room(name: str) -> dict:
    """Create a new chatroom. Idempotent — returns existing room if already created."""
    return _get_service().init_room(name)


@mcp.tool()
def post_message(room: str, sender: str, content: str) -> dict:
    """Post a message to a room. Auto-creates room if missing. Rejects posts to archived rooms."""
    return _get_service().post_message(room, sender, content)


@mcp.tool()
def read_messages(room: str, since_id: int | None = None, limit: int = 100) -> dict:
    """Read messages from a room. Use since_id for incremental polling. Default limit 100."""
    return _get_service().read_messages(room, since_id=since_id, limit=limit)


@mcp.tool()
def list_rooms(status: str = "live") -> dict:
    """List rooms by status. Options: 'live' (default), 'archived', 'all'."""
    return _get_service().list_rooms(status=status)


@mcp.tool()
def archive_room(name: str) -> dict:
    """Archive a room. Sets status to 'archived', keeps all messages."""
    return _get_service().archive_room(name)


@mcp.tool()
def clear_room(name: str) -> dict:
    """Delete all messages in a room. Keeps the room record."""
    return _get_service().clear_room(name)
