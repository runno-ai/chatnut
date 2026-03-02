"""Shared fixtures for agents-chat-mcp tests."""

import pytest
from agents_chat_mcp.db import init_db


@pytest.fixture
def db():
    """In-memory SQLite database for testing."""
    conn = init_db(":memory:")
    yield conn
    conn.close()
