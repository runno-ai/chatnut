#!/usr/bin/env python3
"""Import archived JSONL chatroom files into the SQLite database.

Usage:
    python -m scripts.import_archive --project PROJECT [--archive-dir DIR] [--db-path PATH] [--dry-run]

Arguments:
    --project      Project name to assign all imported rooms to (required)
    --archive-dir  Directory containing .jsonl archive files
                   (default: ~/.agent-chat/archived)
    --db-path      SQLite database path
                   (default: ~/.agent-chat/agent-chat.db or CHAT_DB_PATH env var)
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import uuid
from pathlib import Path

# Add parent to path so we can import agent_chat_mcp
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent_chat_mcp.db import init_db


# Filename pattern: {room-name}-{YYYYMMDD}-{HHMMSS}.jsonl
FILENAME_RE = re.compile(r"^(.+)-(\d{8})-(\d{6})\.jsonl$")


def parse_filename(filename: str) -> tuple[str, str] | None:
    """Extract (room_name, created_at_iso) from filename. Returns None if no match."""
    m = FILENAME_RE.match(filename)
    if not m:
        return None
    room_name = m.group(1)
    date_str = m.group(2)  # YYYYMMDD
    time_str = m.group(3)  # HHMMSS
    created_at = (
        f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        f"T{time_str[:2]}:{time_str[2:4]}:{time_str[4:6]}Z"
    )
    return room_name, created_at


def import_file(conn: sqlite3.Connection, filepath: Path, project: str, *, dry_run: bool = False) -> tuple[int, int]:
    """Import a single JSONL file. Returns (messages_imported, messages_skipped)."""
    project = project.strip()
    if not project:
        raise ValueError("project must be a non-empty string")
    result = parse_filename(filepath.name)
    if result is None:
        print(f"  SKIP (bad filename): {filepath.name}")
        return 0, 0

    room_name, created_at = result

    # Read all records — the old Bun server wrote multi-line JSON (raw newlines
    # inside string values), so we split on record boundaries instead of per-line.
    records = []
    content = filepath.read_text()
    parts = re.split(r"^(?=\{\"ts\")", content, flags=re.MULTILINE)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        try:
            rec = json.loads(part)
        except json.JSONDecodeError:
            # Escape raw newlines/tabs inside JSON string values
            fixed = part.replace("\n", "\\n").replace("\t", "\\t").replace("\r", "\\r")
            try:
                rec = json.loads(fixed)
            except json.JSONDecodeError:
                print(f"  WARN: unparseable record in {filepath.name}")
                continue
        records.append(rec)

    if not records:
        return 0, 0

    if dry_run:
        print(f"  DRY-RUN: {filepath.name} -> project={project}, room={room_name}, {len(records)} msgs")
        return len(records), 0

    # Create room (archived)
    room_id = str(uuid.uuid4())
    conn.execute(
        "INSERT OR IGNORE INTO rooms (id, name, project, status, created_at, archived_at) "
        "VALUES (?, ?, ?, 'archived', ?, ?)",
        (room_id, room_name, project, created_at, created_at),
    )
    # Get actual room_id (may already exist)
    row = conn.execute(
        "SELECT id FROM rooms WHERE project=? AND name=?", (project, room_name)
    ).fetchone()
    room_id = row[0]

    # Insert messages
    imported = 0
    for rec in records:
        ts = rec.get("ts", created_at)
        sender = rec.get("from", "unknown")
        msg = rec.get("msg", "")
        if not msg:
            continue
        exists = conn.execute(
            "SELECT 1 FROM messages WHERE room_id=? AND sender=? AND content=? AND created_at=?",
            (room_id, sender, msg, ts),
        ).fetchone()
        if exists:
            continue
        conn.execute(
            "INSERT INTO messages (room_id, sender, content, message_type, created_at) "
            "VALUES (?, ?, ?, 'message', ?)",
            (room_id, sender, msg, ts),
        )
        imported += 1

    conn.commit()
    return imported, len(records) - imported


def main() -> None:
    parser = argparse.ArgumentParser(description="Import archived JSONL chatrooms into SQLite")
    parser.add_argument(
        "--project",
        required=True,
        help="Project name to assign all imported rooms to",
    )
    parser.add_argument(
        "--archive-dir",
        default=os.path.expanduser("~/.agent-chat/archived"),
        help="Directory containing .jsonl archive files",
    )
    parser.add_argument(
        "--db-path",
        default=os.path.expanduser(os.environ.get("CHAT_DB_PATH", "~/.agent-chat/agent-chat.db")),
        help="SQLite database path",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would be imported without writing")
    args = parser.parse_args()

    project = args.project.strip()
    if not project:
        parser.error("--project must be a non-empty string")

    archive_dir = Path(args.archive_dir)
    if not archive_dir.is_dir():
        print(f"ERROR: archive directory not found: {archive_dir}")
        sys.exit(1)

    jsonl_files = sorted(archive_dir.glob("*.jsonl"))
    if not jsonl_files:
        print("No .jsonl files found.")
        return

    print(f"{'DRY RUN — ' if args.dry_run else ''}Importing {len(jsonl_files)} files from {archive_dir} into project '{project}'")
    print(f"Database: {args.db_path}")
    print()

    conn = init_db(args.db_path)

    total_imported = 0
    total_skipped = 0
    files_imported = 0

    for filepath in jsonl_files:
        imported, skipped = import_file(conn, filepath, project=project, dry_run=args.dry_run)
        total_imported += imported
        total_skipped += skipped
        if imported > 0:
            files_imported += 1

    print()
    print(f"Done: {files_imported} files, {total_imported} messages imported, {total_skipped} skipped")


if __name__ == "__main__":
    main()
