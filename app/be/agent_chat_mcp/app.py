# agent_chat_mcp/app.py
"""FastAPI application — mounts MCP + REST/SSE routes + static file serving."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastmcp.utilities.lifespan import combine_lifespans

logger = logging.getLogger(__name__)

AUTO_ARCHIVE_INTERVAL = 300  # check every 5 minutes
AUTO_ARCHIVE_INACTIVE_SECONDS = 7200  # archive after 2 hours of inactivity

from agent_chat_mcp.db import init_db
from agent_chat_mcp.service import ChatService
from agent_chat_mcp import mcp as mcp_module
from agent_chat_mcp.mcp import mcp
from agent_chat_mcp.routes import create_router

DB_PATH = os.path.expanduser(os.environ.get("CHAT_DB_PATH", "~/.claude/agent-chat.db"))
STATIC_DIR = os.environ.get("STATIC_DIR", os.path.join(os.path.dirname(__file__), "../../fe/dist"))


@lru_cache(maxsize=1)
def _get_service() -> ChatService:
    db_conn = init_db(DB_PATH)
    return ChatService(db_conn)


# Wire MCP tools to use the same service instance as REST routes
mcp_module.set_service_factory(_get_service)

# Get MCP ASGI sub-app — path="/" so mount("/mcp") serves at /mcp (not /mcp/mcp)
mcp_app = mcp.http_app(path="/", transport="streamable-http")


async def _auto_archive_loop() -> None:
    """Periodically archive stale live rooms."""
    while True:
        await asyncio.sleep(AUTO_ARCHIVE_INTERVAL)
        try:
            archived = _get_service().auto_archive_stale_rooms(AUTO_ARCHIVE_INACTIVE_SECONDS)
            if archived:
                names = [r["name"] for r in archived]
                logger.info("Auto-archived %d stale rooms: %s", len(archived), names)
        except Exception:
            logger.exception("Auto-archive failed")


@asynccontextmanager
async def app_lifespan(app):
    # Ensure service is initialized at startup
    _get_service()
    mcp_module.set_event_loop(asyncio.get_running_loop())
    task = asyncio.create_task(_auto_archive_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    mcp_module.set_event_loop(None)  # Clear stale reference; _notify_waiters guards against closed loop


app = FastAPI(
    title="Team Chat",
    lifespan=combine_lifespans(app_lifespan, mcp_app.lifespan),
)

# Mount MCP at /mcp — path="/" in http_app() + mount("/mcp") = /mcp
app.mount("/mcp", mcp_app)

# Mount API routes
api_router = create_router(_get_service)
app.include_router(api_router)


# Serve React SPA — static files + fallback to index.html
@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    static_dir = os.path.abspath(STATIC_DIR)
    file_path = os.path.normpath(os.path.join(static_dir, full_path))
    if not file_path.startswith(static_dir):
        return JSONResponse(status_code=404, content={"error": "Not found"})
    if os.path.isfile(file_path):
        return FileResponse(file_path)
    index_path = os.path.join(static_dir, "index.html")
    if os.path.isfile(index_path):
        return FileResponse(index_path)
    return JSONResponse(status_code=503, content={"error": "Frontend not built. Run: cd app/fe && bun run build"})
