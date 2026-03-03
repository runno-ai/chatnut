"""Shared configuration constants."""

import os

DB_PATH = os.path.expanduser(os.environ.get("CHAT_DB_PATH", "~/.chatnut/chatnut.db"))
