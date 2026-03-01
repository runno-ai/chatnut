"""Shared fixtures for team-chat tests."""

import pytest
from agent_chat_mcp.db import init_db


@pytest.fixture
def db():
    """In-memory SQLite database for testing."""
    conn = init_db(":memory:")
    yield conn
    conn.close()
