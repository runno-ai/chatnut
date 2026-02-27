# team_chat_mcp/app.py
"""FastAPI application — mounts MCP + REST/SSE routes + static file serving."""

import os
from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastmcp.utilities.lifespan import combine_lifespans

from team_chat_mcp.db import init_db
from team_chat_mcp.service import ChatService
from team_chat_mcp import mcp as mcp_module
from team_chat_mcp.mcp import mcp
from team_chat_mcp.routes import create_router

DB_PATH = os.path.expanduser(os.environ.get("CHAT_DB_PATH", "~/.claude/team-chat.db"))
STATIC_DIR = os.environ.get("STATIC_DIR", os.path.join(os.path.dirname(__file__), "../../fe/dist"))


@lru_cache(maxsize=1)
def _get_service() -> ChatService:
    db_conn = init_db(DB_PATH)
    return ChatService(db_conn)


# Wire MCP tools to use the same service instance as REST routes
mcp_module.set_service_factory(_get_service)

# Get MCP ASGI sub-app — path="" so MCP handles at mount root, not double-prefixed
mcp_app = mcp.http_app(path="", transport="streamable-http")


@asynccontextmanager
async def app_lifespan(app):
    # Ensure service is initialized at startup
    _get_service()
    yield


app = FastAPI(
    title="Team Chat",
    lifespan=combine_lifespans(app_lifespan, mcp_app.lifespan),
)

# Mount MCP at /mcp — path="" in http_app() + mount("/mcp") = /mcp (not /mcp/mcp)
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
