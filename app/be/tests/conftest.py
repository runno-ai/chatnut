"""Shared fixtures for chatnut tests."""

import os

import pytest
from chatnut.db import init_db


@pytest.fixture(autouse=True)
def _suppress_browser(monkeypatch):
    """Prevent webbrowser.open from firing during tests."""
    monkeypatch.setenv("CHATNUT_OPEN_BROWSER", "0")


@pytest.fixture
def db():
    """In-memory SQLite database for testing."""
    conn = init_db(":memory:")
    yield conn
    conn.close()
