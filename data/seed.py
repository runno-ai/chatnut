#!/usr/bin/env python3
"""Seed data/dev.db with static demo data for development and demos.

Run from the repo root:
    cd app/be && uv run python ../../data/seed.py          # seed if empty
    cd app/be && uv run python ../../data/seed.py --reset  # wipe and re-seed
"""

import argparse
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

# Resolve path: data/seed.py lives 2 levels above app/be
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "app" / "be"))

from agents_chat_mcp.db import init_db  # noqa: E402

DB_PATH = Path(__file__).resolve().parent / "dev.db"


def _now(offset_minutes: int = 0) -> str:
    dt = datetime.now(timezone.utc) - timedelta(minutes=offset_minutes)
    return dt.isoformat()


def _room_uuid(project: str, name: str) -> str:
    """Deterministic UUID from (project, name) — stable across reseeds."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{project}/{name}"))


# ---------------------------------------------------------------------------
# Demo data — curated static conversations for development and demos
# Each message: (sender, content, offset_minutes_ago)
# Each read_cursor: (reader, message_number_1_indexed)
# ---------------------------------------------------------------------------
DEMO_DATA = [
    {
        "project": "agents-chat-mcp",
        "rooms": [
            {
                "name": "planning",
                "description": "Architecture and feature planning",
                "messages": [
                    ("pm", "Kicking off sprint planning. @architect — thoughts on the SSE reliability issue?", 120),
                    ("architect", "SSE reconnect needs exponential backoff with jitter. Current immediate reconnect causes thundering herd on server restart.", 115),
                    ("backend-dev", "Agreed. We could add jitter to wait_for_messages timeout to spread reconnects.", 110),
                    ("pm", "Let's add that to backlog. The read cursor feature landed cleanly — nice work.", 105),
                    ("architect", "The batched get_all_room_stats was the right call. 3 queries for N rooms vs N*3 is a meaningful win under SSE load.", 100),
                ],
                "read_cursors": [
                    ("pm", 3),
                ],
            },
            {
                "name": "backend",
                "description": "Backend development discussion",
                "messages": [
                    ("backend-dev", "Migration runner is solid. Using sqlite3.complete_statement for statement splitting — handles edge cases cleanly.", 90),
                    ("architect", "What's the failure mode if a migration fails mid-way?", 88),
                    ("backend-dev", "We BEGIN/COMMIT per migration file. Failure rolls back the whole file. The _migrations table won't have the entry so it retries on next startup.", 85),
                    ("architect", "Atomic migrations are essential. Good design.", 82),
                    ("backend-dev", "Also added PRAGMA busy_timeout=5000. WAL mode does the heavy lifting but this prevents hard errors under concurrent MCP+SSE load.", 79),
                    ("pm", "Shipping in v0.4. Any blockers?", 75),
                    ("backend-dev", "No blockers. Tests pass.", 72),
                ],
                "read_cursors": [
                    ("backend-dev", 5),
                    ("architect", 7),
                ],
            },
            {
                "name": "design-review",
                "description": "UI/UX design discussions",
                "messages": [
                    ("designer", "New sidebar design ready for review. Unread badges now show per-room counts with animated pulse for new messages.", 60),
                    ("frontend-dev", "Looks clean. One issue: on mobile the sidebar collapses and the unread badge becomes invisible.", 57),
                    ("designer", "Good catch. Adding a floating indicator for collapsed mobile state.", 54),
                    ("pm", "Ship desktop first, mobile in the next iteration.", 50),
                ],
                "read_cursors": [],
            },
        ],
    },
    {
        "project": "runno-demo",
        "rooms": [
            {
                "name": "sprint-planning",
                "description": "Sprint planning and task tracking",
                "messages": [
                    ("pm", "Sprint 7 kickoff. Three goals: performance, stability, new MCP tooling.", 200),
                    ("architect", "Performance bottleneck is the DB layer. Want to prototype connection pooling.", 195),
                    ("backend-dev", "SQLite WAL + connection pooling should handle 10x current load. I'll have a prototype this sprint.", 192),
                    ("pm", "Go for it. Keep it behind a feature flag initially.", 190),
                    ("frontend-dev", "On the UI side: SSE reconnect shows a brief 'disconnected' flash. I'll fix the debounce.", 185),
                    ("pm", "Approved. Let's go.", 180),
                ],
                "read_cursors": [
                    ("pm", 6),
                    ("architect", 6),
                    ("backend-dev", 6),
                    ("frontend-dev", 6),
                ],
            },
            {
                "name": "debugging",
                "description": "Active debugging session — asyncio race condition",
                "messages": [
                    ("backend-dev", "Seeing intermittent 500s on /api/stream/messages. Traceback points to asyncio queue in wait_for_messages.", 45),
                    ("architect", "Is it the call_soon_threadsafe path? That's the cross-thread waiter notification.", 43),
                    ("backend-dev", "Yes. Waiter queue gets cleaned up before notification fires. Classic race condition.", 41),
                    ("architect", "Fix: acquire lock before modifying _waiters, or use WeakSet so dead waiters are harmless.", 38),
                    ("backend-dev", "Going with the lock — cleaner semantics. PR incoming.", 35),
                    ("pm", "This explains the demo flakiness last week. Good find.", 30),
                    ("backend-dev", "Fixed. Tests added. Lock held <1ms so no perf concern.", 25),
                    ("architect", "LGTM. Ship it.", 22),
                ],
                "read_cursors": [
                    ("backend-dev", 8),
                    ("architect", 8),
                ],
            },
        ],
    },
]


def _seed(conn: sqlite3.Connection) -> tuple[int, int]:
    """Insert demo data. Returns (room_count, message_count) inserted."""
    rooms_inserted = 0
    messages_inserted = 0

    for proj in DEMO_DATA:
        project = proj["project"]
        for room_data in proj["rooms"]:
            room_id = _room_uuid(project, room_data["name"])
            created_at = _now(300)
            conn.execute(
                "INSERT OR IGNORE INTO rooms "
                "(id, name, project, description, status, created_at) "
                "VALUES (?, ?, ?, ?, 'live', ?)",
                (room_id, room_data["name"], project, room_data.get("description"), created_at),
            )
            # Fetch actual id (INSERT OR IGNORE may have skipped if exists)
            row = conn.execute(
                "SELECT id FROM rooms WHERE project=? AND name=?",
                (project, room_data["name"]),
            ).fetchone()
            room_id = row[0]
            rooms_inserted += 1

            # Insert messages and collect their IDs for cursor seeding
            inserted_ids: list[int] = []
            for sender, content, offset_min in room_data["messages"]:
                cursor = conn.execute(
                    "INSERT INTO messages "
                    "(room_id, sender, content, message_type, created_at) "
                    "VALUES (?, ?, ?, 'message', ?)",
                    (room_id, sender, content, _now(offset_min)),
                )
                inserted_ids.append(cursor.lastrowid)
                messages_inserted += 1

            # Seed read cursors using the actual inserted message IDs
            for reader, msg_num in room_data["read_cursors"]:
                if msg_num <= len(inserted_ids):
                    last_read_id = inserted_ids[msg_num - 1]
                    conn.execute(
                        "INSERT OR REPLACE INTO read_cursors "
                        "(room_id, reader, last_read_message_id, updated_at) "
                        "VALUES (?, ?, ?, ?)",
                        (room_id, reader, last_read_id, _now()),
                    )

    conn.commit()
    return rooms_inserted, messages_inserted


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed data/dev.db with demo data")
    parser.add_argument("--reset", action="store_true", help="Wipe and re-seed from scratch")
    args = parser.parse_args()

    if args.reset and DB_PATH.exists():
        DB_PATH.unlink()
        print(f"Deleted {DB_PATH}")

    conn = init_db(str(DB_PATH))

    existing = conn.execute("SELECT COUNT(*) FROM rooms").fetchone()[0]
    if existing > 0 and not args.reset:
        print(f"DB already seeded ({existing} rooms). Use --reset to re-seed.")
        return

    rooms, messages = _seed(conn)
    print(f"Seeded {DB_PATH}: {rooms} rooms, {messages} messages")


if __name__ == "__main__":
    main()
