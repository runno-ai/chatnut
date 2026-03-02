# Go Public Prep Implementation Plan

## Context

The `agent-chat-mcp` project is being prepared for open-source release. Three blocking issues stand between the current private repo and a clean public release: missing legal metadata (no LICENSE, incomplete pyproject.toml), code correctness issues (fastmcp version pinned too loosely, default DB path inside `~/.claude/` which is a Claude-specific dir), and internal references scattered through config/docs (old package name `team_chat_mcp`, hardcoded internal project names, personal skill paths).

## Goal

Deliver a legally complete, technically correct, internally clean codebase ready for public release on GitHub.

## Architecture

All three tasks are fully independent file-level changes with no code logic — no new abstractions, no schema changes, no API changes. Task 1 adds files + metadata (owns all `pyproject.toml` changes). Task 2 updates default strings in three source files. Task 3 deletes one file and updates configs/scripts. All three can execute in parallel.

## Affected Areas

- Backend: `app/be/pyproject.toml`, `app/be/agent_chat_mcp/app.py`, `app/be/agent_chat_mcp/mcp.py`, `app/be/scripts/import_archive.py`
- Config/docs: `LICENSE`, `SKILL.md`, `.coderabbit.yaml`, `CLAUDE.md`, `README.md`, `docs/skill-migration.md`

## Key Files

- `app/be/pyproject.toml` — ALL metadata + version changes go here (Task 1 owns this file entirely)
- `app/be/agent_chat_mcp/app.py` — default DB path (Task 2)
- `app/be/agent_chat_mcp/mcp.py` — duplicate default DB path (Task 2)
- `.coderabbit.yaml` — stale package name references (Task 3)
- `app/be/scripts/import_archive.py` — hardcoded internal project names + `~/.claude/` defaults (Task 3)

## Reusable Utilities

- `app/be/agent_chat_mcp/app.py:DB_PATH` — existing constant being updated, same pattern used by `mcp.py`

---

## Tasks

### Task 1: Legal & Project Metadata (MCP-1)

**Parallel with Tasks 2 and 3 — no interdependencies.**
**Owns ALL `pyproject.toml` changes** (both metadata and fastmcp version pin from MCP-2).

**Files:**
- Create: `LICENSE`
- Modify: `app/be/pyproject.toml` — add `authors`, `license`, `[project.urls]`, bump `fastmcp>=3.0.0`

**Step 1: Create MIT LICENSE**

Create `LICENSE` at the repo root with this exact content:

```
MIT License

Copyright (c) 2025 Runno AI

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

**Step 2: Update pyproject.toml — add authors, license, urls, AND fix fastmcp version**

In `app/be/pyproject.toml`, make these changes together in one edit:

a) In the `[project]` table, after `description`, add:
```toml
authors = [
    { name = "Runno AI", email = "hi@runno.dev" },
]
license = { text = "MIT" }
```

b) In the `[project]` dependencies list, change:
```
"fastmcp>=2.0.0",
```
to:
```
"fastmcp>=3.0.0",
```

c) Add a new `[project.urls]` table:
```toml
[project.urls]
Repository = "https://github.com/runno-ai/agent-chat-mcp"
Homepage = "https://github.com/runno-ai/agent-chat-mcp"
```

**Step 3: Verify pyproject.toml parses correctly**

```bash
cd /Users/tushuyang/agent-chat-mcp/.worktrees/go-public-prep/app/be && uv run python -c "
import tomllib
data = tomllib.load(open('pyproject.toml', 'rb'))
assert data['project']['license'] == {'text': 'MIT'}, 'Missing license'
assert 'authors' in data['project'], 'Missing authors'
assert 'urls' in data['project'], 'Missing urls'
deps = data['project']['dependencies']
fastmcp = [d for d in deps if 'fastmcp' in d][0]
assert '3.0.0' in fastmcp, f'Bad fastmcp version: {fastmcp}'
print('pyproject.toml OK')
"
```

Expected: `pyproject.toml OK`

**Step 4: Commit**

```bash
cd /Users/tushuyang/agent-chat-mcp/.worktrees/go-public-prep
git add LICENSE app/be/pyproject.toml
git commit -m "chore: add MIT LICENSE and complete pyproject.toml metadata (MCP-1)"
```

---

### Task 2: Code Correctness — DB Path & Source Cleanup (MCP-2)

**Parallel with Tasks 1 and 3 — no interdependencies.**
**Does NOT modify `pyproject.toml`** — that is owned entirely by Task 1.

**Files:**
- Modify: `app/be/agent_chat_mcp/app.py` — change default DB path
- Modify: `app/be/agent_chat_mcp/mcp.py` — change default DB path
- Modify: `CLAUDE.md` — update default path + project name in line 5
- Modify: `README.md` — update default DB path

**Step 1: Update default DB path in app.py**

In `app/be/agent_chat_mcp/app.py`, change:
```python
DB_PATH = os.path.expanduser(os.environ.get("CHAT_DB_PATH", "~/.claude/agent-chat.db"))
```
to:
```python
DB_PATH = os.path.expanduser(os.environ.get("CHAT_DB_PATH", "~/.agent-chat/agent-chat.db"))
```

**Step 2: Update default DB path in mcp.py**

In `app/be/agent_chat_mcp/mcp.py`, change:
```python
DB_PATH = os.path.expanduser(os.environ.get("CHAT_DB_PATH", "~/.claude/agent-chat.db"))
```
to:
```python
DB_PATH = os.path.expanduser(os.environ.get("CHAT_DB_PATH", "~/.agent-chat/agent-chat.db"))
```

**Step 3: Update CLAUDE.md**

In `CLAUDE.md`:

a) Line 5 — project overview says "Team Chat MCP". Change to "Agent Chat MCP":
```
## Project Overview

Agent Chat MCP — unified FastAPI server for agent team chatrooms.
```

b) In the Environment Variables table, change:
```
| `CHAT_DB_PATH` | SQLite database file path | `~/.claude/agent-chat.db` |
```
to:
```
| `CHAT_DB_PATH` | SQLite database file path | `~/.agent-chat/agent-chat.db` |
```

**Step 4: Update README.md**

In `README.md`, change the default `CHAT_DB_PATH` value from `~/.claude/agent-chat.db` to `~/.agent-chat/agent-chat.db`. Find and update any occurrences of `~/.claude/agent-chat.db` in the README.

**Step 5: Run backend tests to confirm nothing broke**

```bash
cd /Users/tushuyang/agent-chat-mcp/.worktrees/go-public-prep/app/be && uv run pytest -x -q
```

Expected: all tests pass (tests use in-memory SQLite DB — the path constant change has no effect on test execution)

**Step 6: Commit**

```bash
cd /Users/tushuyang/agent-chat-mcp/.worktrees/go-public-prep
git add app/be/agent_chat_mcp/app.py app/be/agent_chat_mcp/mcp.py CLAUDE.md README.md
git commit -m "fix: change default DB path to ~/.agent-chat/ (vendor-neutral) (MCP-2)"
```

---

### Task 3: Scrub Internal References (MCP-3)

**Parallel with Tasks 1 and 2 — no interdependencies.**

**Files:**
- Delete: `docs/skill-migration.md`
- Modify: `.coderabbit.yaml` — fix package name, remove DESIGN.md entry
- Modify: `app/be/scripts/import_archive.py` — remove detect_project(), update ~/.claude/ defaults, make --project required
- Modify: `SKILL.md` — rename front matter, fix heading, update both ~/.claude/ refs
- Modify: `CLAUDE.md` — remove personal skill path reference from Dual-Update Rule section

**Step 1: Delete docs/skill-migration.md**

```bash
rm /Users/tushuyang/agent-chat-mcp/.worktrees/go-public-prep/docs/skill-migration.md
```

This file documents an internal portless/launchd setup specific to the author's machine — not useful to the public.

**Step 2: Fix .coderabbit.yaml**

Make these changes to `.coderabbit.yaml`:

a) Replace all `team_chat_mcp/` occurrences with `agent_chat_mcp/` in the `path_instructions` section:
- `app/be/team_chat_mcp/db.py` → `app/be/agent_chat_mcp/db.py`
- `app/be/team_chat_mcp/service.py` → `app/be/agent_chat_mcp/service.py`
- `app/be/team_chat_mcp/mcp.py` → `app/be/agent_chat_mcp/mcp.py`
- `app/be/team_chat_mcp/app.py` → `app/be/agent_chat_mcp/app.py`
- `app/be/team_chat_mcp/routes.py` → `app/be/agent_chat_mcp/routes.py`

b) Remove the entire `DESIGN.md` `path_instructions` block (the block with `- path: 'DESIGN.md'` and its instructions). There is no `DESIGN.md` in this project.

c) Update the documentation convention note in `high_level_summary_instructions` to remove the `DESIGN.md` reference:
```yaml
    ## CRITICAL: Documentation Convention
    This project uses CLAUDE.md at the root for documentation.
    Plans live in docs/plans/. Do NOT flag missing README files.
    - PREFER updating existing docs over suggesting new ones
    - Check if CLAUDE.md needs updates based on code changes
```

**Step 3: Refactor import_archive.py**

Make these changes to `app/be/scripts/import_archive.py`:

a) Update the module docstring (lines 8-9) to remove `~/.claude/` defaults:
```python
"""Import archived JSONL chatroom files into the SQLite database.

Usage:
    python -m scripts.import_archive --project PROJECT [--archive-dir DIR] [--db-path PATH] [--dry-run]

Arguments:
    --project      Project name to assign all imported rooms to (required)
    --archive-dir  Directory containing .jsonl archive files
    --db-path      SQLite database path (default: ~/.agent-chat/agent-chat.db or CHAT_DB_PATH env var)
"""
```

b) Remove the `detect_project()` function entirely (lines 31–48).

c) Update `import_file()` to accept `project: str` as a required parameter, removing the `detect_project()` call:

```python
def import_file(conn: sqlite3.Connection, filepath: Path, project: str, dry_run: bool = False) -> tuple[int, int]:
    """Import a single JSONL file. Returns (messages_imported, messages_skipped)."""
    result = parse_filename(filepath.name)
    if result is None:
        print(f"  SKIP (bad filename): {filepath.name}")
        return 0, 0

    room_name, created_at = result
    # (remove the detect_project() call and the 'if project is None: return None' block)
```

d) Update `main()` to add `--project` as a required argument:
```python
parser.add_argument(
    "--project",
    required=True,
    help="Project name to assign all imported rooms to",
)
```

e) Update the `--archive-dir` default from `~/.claude/agent-chat/archived` to `~/.agent-chat/archived`:
```python
parser.add_argument(
    "--archive-dir",
    default=os.path.expanduser("~/.agent-chat/archived"),
    help="Directory containing .jsonl archive files",
)
```

f) Update the `--db-path` default from `~/.claude/agent-chat.db` to `~/.agent-chat/agent-chat.db`:
```python
parser.add_argument(
    "--db-path",
    default=os.path.expanduser(os.environ.get("CHAT_DB_PATH", "~/.agent-chat/agent-chat.db")),
    help="SQLite database path",
)
```

g) Update `main()` to pass `args.project` to `import_file()`:
```python
imported, skipped = import_file(conn, filepath, project=args.project, dry_run=args.dry_run)
```

h) Update `main()` print statement to include project:
```python
print(f"{'DRY RUN — ' if args.dry_run else ''}Importing {len(jsonl_files)} files from {archive_dir} into project '{args.project}'")
```

**Step 4: Update SKILL.md**

Make these changes to `SKILL.md`:

a) Update front matter (lines 1–6):
```yaml
---
name: agent-chat
title: agent-chat
description: Use when spawning agent teams that need shared discussion visibility beyond hub-and-spoke DMs
aliases: [agent-chat]
---
```

b) Update the heading (line 9):
```markdown
# Agent Chat
```

c) Update the Storage line (line 13) — first occurrence:
```markdown
**Storage:** SQLite database at `~/.agent-chat/agent-chat.db` (WAL mode). Safe from Claude Code's `TeamDelete`.
```

d) Find and update the second `~/.claude/agent-chat.db` reference (line ~172) — same replacement.

**Step 5: Clean CLAUDE.md — remove personal skill path reference**

In `CLAUDE.md`, find the "## SKILL.md Dual-Update Rule" section and replace it:

**Before:**
```markdown
## SKILL.md Dual-Update Rule

When adding or modifying MCP tools:

1. Update `SKILL.md` in this repo (the in-repo copy)
2. Update `~/.claude-chan/skills/team-chat/SKILL.md` (the global skill copy)

Both files must stay in sync. The in-repo `SKILL.md` is the source of truth; copy relevant sections to the global skill after each change.
```

**After:**
```markdown
## SKILL.md

The in-repo `SKILL.md` documents all MCP tools, their signatures, and usage patterns. Keep it updated when adding or modifying MCP tools.
```

**Step 6: Verify tests still pass**

```bash
cd /Users/tushuyang/agent-chat-mcp/.worktrees/go-public-prep/app/be && uv run pytest -x -q
```

Expected: all tests pass

**Step 7: Commit**

```bash
cd /Users/tushuyang/agent-chat-mcp/.worktrees/go-public-prep
git add .coderabbit.yaml app/be/scripts/import_archive.py SKILL.md CLAUDE.md
git rm docs/skill-migration.md
git commit -m "chore: scrub internal references from configs, docs, and scripts (MCP-3)"
```

---

### Phase 4: Documentation Update

- [x] `CLAUDE.md` updated inline (Tasks 2 and 3)
- [x] `SKILL.md` updated inline (Task 3)
- [x] `README.md` DB path updated inline (Task 2)
- [ ] Verify no remaining `~/.claude/agent-chat` references outside `docs/plans/` (covered in Verification)

---

## Verification

After all three tasks complete, run these checks:

```bash
BASE=/Users/tushuyang/agent-chat-mcp/.worktrees/go-public-prep

# 1. LICENSE exists
ls $BASE/LICENSE

# 2. pyproject.toml is valid with MIT license, authors, urls, fastmcp>=3.0.0
cd $BASE/app/be && uv run python -c "
import tomllib
data = tomllib.load(open('pyproject.toml', 'rb'))
assert data['project']['license'] == {'text': 'MIT'}, 'Missing license'
assert 'authors' in data['project'], 'Missing authors'
assert 'urls' in data['project'], 'Missing urls'
deps = data['project']['dependencies']
fastmcp = [d for d in deps if 'fastmcp' in d][0]
assert '3.0.0' in fastmcp, f'Bad fastmcp version: {fastmcp}'
print('pyproject.toml OK')
"

# 3. DB path defaults changed (must show ~/.agent-chat/, NOT ~/.claude/)
grep -n "agent-chat.db" $BASE/app/be/agent_chat_mcp/app.py
grep -n "agent-chat.db" $BASE/app/be/agent_chat_mcp/mcp.py
grep -n "agent-chat.db" $BASE/app/be/scripts/import_archive.py

# 4. No team_chat_mcp remaining (excluding docs/plans/ which have historical refs)
grep -r "team_chat_mcp" $BASE/ --include="*.py" --include="*.yaml" --include="*.toml" --include="*.md" \
  --exclude-dir=".git" \
  | grep -v "docs/plans/"
# Expected: no output

# 5. No ~/.claude/ remaining in source files (excluding docs/plans/)
grep -r "~/.claude/" $BASE/ --include="*.py" --include="*.yaml" --include="*.md" --include="*.toml" \
  --exclude-dir=".git" \
  | grep -v "docs/plans/"
# Expected: no output

# 6. skill-migration.md deleted
ls $BASE/docs/skill-migration.md 2>&1
# Expected: No such file or directory

# 7. SKILL.md front matter has agent-chat
head -6 $BASE/SKILL.md
# Expected: name: agent-chat

# 8. Backend tests
cd $BASE/app/be && uv run pytest -x -q
# Expected: all tests pass

# 9. Frontend tests
cd $BASE/app/fe && bun run test
# Expected: all tests pass

# 10. import_archive.py smoke test
cd $BASE/app/be && uv run python -m scripts.import_archive 2>&1 | grep -i "error\|required\|project"
# Expected: error indicating --project is required
cd $BASE/app/be && uv run python -m scripts.import_archive --project foo --archive-dir /tmp --dry-run 2>&1
# Expected: "No .jsonl files found" or similar (not a crash)
```

Expected: LICENSE present, pyproject.toml valid with MIT + authors + urls + fastmcp>=3.0.0, all DB paths updated to `~/.agent-chat/`, no `team_chat_mcp` refs, no `~/.claude/` refs (in source), skill-migration.md gone, SKILL.md says `agent-chat`, all 173 backend tests pass, frontend tests pass, import_archive.py requires `--project`.

## AI Review Findings

| Severity | Source | Finding | Action |
|----------|--------|---------|--------|
| Critical | Codex + Architect | `import_archive.py` has `~/.claude/` in docstring (lines 8-9) and argparse defaults (lines 149, 154) | Fixed in Task 3, Step 3 |
| Critical | Architect | `SKILL.md` line 172 has second `~/.claude/agent-chat.db` reference | Fixed in Task 3, Step 4d |
| Critical | Architect | `SKILL.md` heading `# Team Chat` not renamed | Fixed in Task 3, Step 4b |
| Critical | Architect | `README.md` DB path update was only a checkbox, not a concrete step | Promoted to Task 2, Step 4 |
| Critical | Architect + Codex | Tasks 1 and 2 both modified `pyproject.toml` — ownership conflict | Resolved: Task 1 owns all `pyproject.toml` changes |
| Critical | Codex | Verification grep would false-positive on `docs/plans/` archived files | Fixed: greps now exclude `docs/plans/` |
| Warning | Architect | `CLAUDE.md` line 5 still says "Team Chat MCP" | Fixed in Task 2, Step 3a |
| Warning | Codex | `import_archive.py` behavioral change needs smoke test | Added to Verification steps 10 |
| Warning | Gemini | Frontend tests missing from verification | Added to Verification step 9 |
| Warning | Architect | Task 3 `git add -A` is too broad | Fixed to explicit `git add` + `git rm` |
