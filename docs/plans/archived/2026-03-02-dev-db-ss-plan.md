# Dev DB Fixture + ss Enhancement Implementation Plan

## Context

The agents-chat service has a single SQLite prod DB (`~/.agents-chat/agents-chat.db`) with no
dev-specific fixture. The current `ss` option 4 for agents-chat calls `_handle_dev` which looks
for a non-existent `scripts/start_full_stack.py`, silently failing. This plan adds a committed
demo DB (`data/dev.db`), a seed script to generate it, a dev start script pointing to it, and
updates `ss` to present a symmetric PROD/DEV menu for agents-chat.

## Goal

Introduce `data/dev.db` (committed demo fixture), `data/seed.py` (curated seed script),
`start-server-dev.sh` (dev start wrapper), and a PROD/DEV `ss` menu for agents-chat — matching
the runno/pbimate pattern.

## Architecture

`data/seed.py` imports `init_db` from `agents_chat_mcp.db` (applies migrations, creates tables),
then inserts static demo data via direct sqlite3. The dev server (`start-server-dev.sh`) is
identical to prod's `start-server.sh` but sets `CHAT_DB_PATH` to the repo's `data/dev.db`.
`_agents_chat_ss` in `portless.sh` replaces the broken `_handle_dev` call: PROD opens the URL
only (never touches the always-on service), DEV starts the `agents-chat-dev` portless route
on demand.

## Affected Areas

- Backend: `data/seed.py` (new), `data/dev.db` (new committed artifact)
- Infra: `~/.claude/skills/agents-chat/start-server-dev.sh` (new), `~/.claude/skills/shell/workspace/portless.sh` (modified)

## Key Files

- `~/.claude/skills/agents-chat/start-server.sh` — prod start script (reference for dev variant)
- `~/.claude/skills/shell/workspace/portless.sh` — `ss` function + `_handle_dev` (to be extended)
- `app/be/agents_chat_mcp/db.py` — `init_db()` entry point for migrations + connection
- `app/be/agents_chat_mcp/app.py` — reads `CHAT_DB_PATH` env var
- `app/be/migrations/` — SQL migration files that init_db applies

## Reusable Utilities

- `app/be/agents_chat_mcp/db.init_db(db_path)` — opens DB, applies migrations, returns connection
- `portless.sh:_portless_is_running(name)` — checks if a portless route is active
- `portless.sh:_portless_kill(name)` — kills a portless route by name
- `portless.sh:_portless_ensure_proxy()` — ensures portless proxy is up
- `portless.sh:_wait_and_open(url, max)` — waits for URL health then opens browser
- `portless.sh:_portless_url(name)` — returns `http://<name>.localhost:1355`

---

## Tasks

### Task 1: Create data/seed.py

**Files:**
- Create: `data/seed.py`
- No test file (verified by running and inspecting DB)

**Step 1: Write seed.py**

```python
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
```

**Step 2: Verify seed script works**

```bash
cd /Users/tushuyang/agents-chat-mcp/main/app/be && uv run python ../../data/seed.py --reset
```

Expected output:
```
Seeded .../data/dev.db: 5 rooms, 25 messages
```

Then verify DB contents:
```bash
sqlite3 /Users/tushuyang/agents-chat-mcp/main/data/dev.db \
  "SELECT project, name, (SELECT COUNT(*) FROM messages m WHERE m.room_id=r.id) as msg_count FROM rooms r ORDER BY project, name;"
```

Expected:
```
agents-chat-mcp|backend|7
agents-chat-mcp|design-review|4
agents-chat-mcp|planning|5
runno-demo|debugging|8
runno-demo|sprint-planning|6
```

**Step 3: Commit seed script**

```bash
cd /Users/tushuyang/agents-chat-mcp/main
git add data/seed.py
git commit -m "feat: add data/seed.py — curated demo DB seed script"
```

---

### Task 2: Seed and commit data/dev.db

**Files:**
- Create: `data/dev.db` (binary artifact, committed)
- Modify: `.gitattributes` (ensure SQLite binary is treated as binary, no line-ending conversion)

**Step 1: Check/update .gitattributes**

```bash
cd /Users/tushuyang/agents-chat-mcp/main
cat .gitattributes 2>/dev/null || echo "(none)"
```

If `*.db` or `data/dev.db` is not listed as binary, add:

```bash
echo 'data/dev.db binary' >> .gitattributes
```

**Step 2: Override the `*.db` gitignore rule for data/dev.db**

`.gitignore` contains `*.db` (line 8) which blocks all SQLite files. Add a negation override:

```bash
cd /Users/tushuyang/agents-chat-mcp/main
echo '!data/dev.db' >> .gitignore
```

Verify the override works:
```bash
git check-ignore -v data/dev.db
# Expected: no output (file is no longer ignored)
# If still ignored, verify negation rule was appended correctly
```

**Step 3: Run seed and commit**

```bash
cd /Users/tushuyang/agents-chat-mcp/main/app/be && uv run python ../../data/seed.py --reset
cd /Users/tushuyang/agents-chat-mcp/main
git add .gitignore .gitattributes data/dev.db
git commit -m "feat: add data/dev.db — committed demo fixture DB"
```

Verify:
```bash
git show --stat HEAD | grep dev.db
# Expected: data/dev.db | Bin 0 -> NNNN bytes (added)
```

---

### Task 3: Create start-server-dev.sh

**Files:**
- Create: `~/.claude/skills/agents-chat/start-server-dev.sh`

**Step 1: Create the script**

```bash
#!/usr/bin/env bash
# start-server-dev.sh — Dev mode: serves against the committed dev fixture DB.
# CHAT_DB_PATH points to data/dev.db in the agents-chat-mcp repo.
exec env CHAT_DB_PATH="$HOME/agents-chat-mcp/main/data/dev.db" \
  /Users/tushuyang/agents-chat-mcp/main/app/be/.venv/bin/python \
  -m uvicorn agents_chat_mcp.app:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}"
```

**Step 2: Make it executable**

```bash
chmod +x ~/.claude/skills/agents-chat/start-server-dev.sh
```

**Step 3: Verify**

Confirm CHAT_DB_PATH is set correctly by checking against the prod script:
```bash
diff ~/.claude/skills/agents-chat/start-server.sh \
     ~/.claude/skills/agents-chat/start-server-dev.sh
```

Expected diff: only the `exec env CHAT_DB_PATH=...` line differs.

No commit needed — this file lives outside the repo.

---

### Task 4: Update portless.sh — add _agents_chat_ss, update ss

**Files:**
- Modify: `~/.claude/skills/shell/workspace/portless.sh`

**Step 1: Add `_agents_chat_ss` function**

Insert the new function immediately before the `ss()` function in `portless.sh`:

```bash
# --- agents-chat PROD/DEV launcher ---
# PROD: always-on portless service — ss opens the URL but never starts/stops it.
# DEV:  on-demand portless route pointing to data/dev.db in the repo.
_agents_chat_ss() {
  local prod_name="agents-chat"
  local dev_name="agents-chat-dev"
  local dev_scripts_dir="$HOME/.claude/skills/agents-chat"
  local prod_url
  prod_url=$(_portless_url "$prod_name")
  local dev_url
  dev_url=$(_portless_url "$dev_name")

  # Status indicators
  local prod_ind=""
  _portless_is_running "$prod_name" && prod_ind=" \033[0;32m● $prod_url\033[0m"
  local dev_ind=""
  _portless_is_running "$dev_name" && dev_ind=" \033[0;32m● $dev_url\033[0m"

  echo "\033[1;36magents-chat — Select mode:\033[0m"
  echo ""
  printf "  \033[1;33m1)\033[0m PROD  %s%b\n" "$prod_name" "$prod_ind"
  printf "  \033[1;33m2)\033[0m DEV   %s%b\n" "$dev_name" "$dev_ind"
  echo ""
  echo -n "Select (1-2): "
  read -r selection

  case "$selection" in
    1)
      if _portless_is_running "$prod_name"; then
        echo "\033[0;32m→ Opening $prod_url\033[0m"
        open "$prod_url"
      else
        echo "\033[0;31mProd service is not running. It is an always-on portless service — start it separately.\033[0m"
      fi
      ;;
    2)
      if _portless_is_running "$dev_name"; then
        echo ""
        printf "\033[1;33mWarning:\033[0m \033[1;36m%s\033[0m already running at \033[4m%s\033[0m\n" "$dev_name" "$dev_url"
        echo -n "Force restart? [y/N]: "
        read -r answer
        if [[ "$answer" =~ ^[Yy]$ ]]; then
          echo "\033[0;90mStopping $dev_name...\033[0m"
          _portless_kill "$dev_name"
          sleep 1
        else
          echo "\033[0;32m→ Opening $dev_url\033[0m"
          open "$dev_url"
          return 0
        fi
      fi

      _portless_ensure_proxy

      echo "\033[0;32m→ Starting $dev_name\033[0m"
      echo "\033[0;90m  dir: $dev_scripts_dir\033[0m"
      echo "\033[0;90m  url: $dev_url\033[0m"

      local _saved_cwd="$PWD"
      cd "$dev_scripts_dir" || return 1
      portless "$dev_name" "./start-server-dev.sh" &
      disown
      cd "$_saved_cwd"

      "$HOME/.portless/bin/portless-registry" refresh &>/dev/null &
      disown

      ( _wait_and_open "$dev_url" 90 ) &>/dev/null &
      disown

      echo "\033[0;32m→ Server starting in background. Browser opens when ready.\033[0m"
      ;;
    *)
      echo "\033[0;31mInvalid selection\033[0m"
      return 1
      ;;
  esac
}
```

**Step 2: Update `ss` option 4**

Change the existing `ss()` function's option 4 from:
```bash
4) _handle_dev "agents-chat" "agents-chat" "$HOME/agents-chat-mcp/main" "$@" ;;
```
to:
```bash
4) _agents_chat_ss "$@" ;;
```

**Step 3: Reload and verify**

```bash
source ~/.zshrc
ss
# Select 4 (agents-chat) → should see PROD/DEV menu
```

Expected output for option 4:
```
agents-chat — Select mode:

  1) PROD  agents-chat        ● http://agents-chat.localhost:1355
  2) DEV   agents-chat-dev

Select (1-2):
```

No commit needed — this file lives outside the repo.

---

### Phase 5: Documentation Update

- [ ] Update `CLAUDE.md` / `SKILL.md` to document the dev DB, seed script, and how to reset it
- [ ] Add a note to `~/.claude/rules/server-management.md` — list `agents-chat-dev` as a known service
- [ ] Update the Known Services table in `server-management.md`:
  ```
  | `agents-chat-dev` | dev | `~/agents-chat-mcp/main/data/dev.db` |
  ```

---

## Verification

After all tasks complete, run the full end-to-end check:

```bash
# 1. Verify seed script
cd /Users/tushuyang/agents-chat-mcp/main/app/be
uv run python ../../data/seed.py --reset
# Expected: "Seeded .../data/dev.db: 5 rooms, 25 messages"

# 2. Verify dev DB is committed
cd /Users/tushuyang/agents-chat-mcp/main
git status data/dev.db
# Expected: nothing to commit (file is tracked)

# 3. Verify start-server-dev.sh is executable
ls -la ~/.claude/skills/agents-chat/start-server-dev.sh
# Expected: -rwxr-xr-x

# 4. Source and test ss
source ~/.zshrc
# Manually run: ss → 4 → should see PROD/DEV menu
# Select 2 (DEV) → verify agents-chat-dev starts
# Open http://agents-chat-dev.localhost:1355 → verify demo data loads

# 5. Verify dev and prod run independently
# Both agents-chat and agents-chat-dev can run simultaneously
# Prod DB remains ~/.agents-chat/agents-chat.db (unchanged)
# Dev DB is ~/agents-chat-mcp/main/data/dev.db
```

Expected: dev server shows 5 demo rooms across 2 projects. Prod server unaffected.

## AI Review Findings

| Severity | Source | Finding | Action |
|----------|--------|---------|--------|
| Critical | Architect | `.gitignore` line 8 has `*.db` — silently blocks `git add data/dev.db` | Fixed in Task 2 Step 2: add `!data/dev.db` negation before committing |
| Critical | Architect + Codex + Gemini | `uuid4()` generates random room IDs — unstable across reseeds, breaks any reference by ID | Fixed in Task 1: changed to `uuid5(NAMESPACE_DNS, f"{project}/{name}")` — deterministic and reproducible |
| Warning | Codex | `--reset` deletes file and reinits DB — AUTOINCREMENT counters reset to 1 | Acceptable; read cursors seeded from actual inserted IDs so consistency is maintained |
| Warning | Architect | `_agents_chat_ss` duplicates `_handle_dev` logic (force-restart, proxy, launch, open) | Acceptable — agents-chat PROD model is unique enough to warrant a bespoke handler; refactor deferred |
| Suggestion | Codex | Add `--check` / `--db-path` flags to seed.py | Deferred — out of scope for this iteration |
| Suggestion | Gemini | Document `seed.py --reset` workflow in README | Covered by Phase 5 docs update |
| Rejected | Gemini | Gitignore `data/dev.db` instead of committing | User explicitly wants it committed; .gitattributes marks binary |
| Rejected | Codex | Migrations directory missing | Verified: `app/be/migrations/` exists with `001_initial.sql` + `002_read_cursors.sql` |
| Rejected | Gemini | `portless.sh` not found | Verified: `~/.claude/skills/shell/workspace/portless.sh` exists (319 lines) |
