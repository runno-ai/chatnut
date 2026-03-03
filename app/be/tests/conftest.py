"""Shared fixtures for chatnut tests."""

import pytest
from chatnut.db import init_db


@pytest.fixture
def db():
    """In-memory SQLite database for testing."""
    conn = init_db(":memory:")
    yield conn
    conn.close()
