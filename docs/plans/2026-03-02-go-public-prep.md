# Go Public Prep Implementation Plan

## Context

The `agent-chat-mcp` project is being prepared for open-source release. Three blocking issues stand between the current private repo and a clean public release: missing legal metadata (no LICENSE, incomplete pyproject.toml), code correctness issues (fastmcp version pinned too loosely, default DB path inside `~/.claude/` which is a Claude-specific dir), and internal references scattered through config/docs (old package name `team_chat_mcp`, hardcoded internal project names, personal skill paths).

## Goal

Deliver a legally complete, technically correct, internally clean codebase ready for public release on GitHub.

## Architecture

All three tasks are fully independent file-level changes with no code logic — no new abstractions, no schema changes, no API changes. Task 1 adds files + metadata. Task 2 updates two default strings and one version pin. Task 3 deletes one file and updates configs. All three can execute in parallel.

## Affected Areas

- Backend: `app/be/pyproject.toml`, `app/be/agent_chat_mcp/app.py`, `app/be/agent_chat_mcp/mcp.py`, `app/be/scripts/import_archive.py`
- Config/docs: `LICENSE`, `SKILL.md`, `.coderabbit.yaml`, `CLAUDE.md`, `docs/skill-migration.md`

## Key Files

- `app/be/pyproject.toml` — touched by both Task 1 (authors/license/urls) and Task 2 (fastmcp version)
- `app/be/agent_chat_mcp/app.py` — default DB path (Task 2)
- `app/be/agent_chat_mcp/mcp.py` — duplicate default DB path (Task 2)
- `.coderabbit.yaml` — stale package name references (Task 3)
- `app/be/scripts/import_archive.py` — hardcoded internal project names (Task 3)

## Reusable Utilities

- `app/be/agent_chat_mcp/app.py:DB_PATH` — existing constant being updated, same pattern used by `mcp.py`

---

## Tasks

### Task 1: Legal & Project Metadata (MCP-1)

**Parallel with Tasks 2 and 3 — no interdependencies.**

**Files:**
- Create: `LICENSE`
- Modify: `app/be/pyproject.toml` — add `authors`, `license`, `[project.urls]`

**Step 1: Create MIT LICENSE**

```
Create LICENSE with content:
```

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

**Step 2: Update pyproject.toml — add authors, license, urls**

In `app/be/pyproject.toml`, in the `[project]` table after `description`, add:

```toml
authors = [
    { name = "Runno AI", email = "hi@runno.dev" },
]
license = { text = "MIT" }
```

And add a new `[project.urls]` table:

```toml
[project.urls]
Repository = "https://github.com/runno-ai/agent-chat-mcp"
Homepage = "https://github.com/runno-ai/agent-chat-mcp"
```

**Step 3: Verify pyproject.toml parses**

```bash
cd /Users/tushuyang/agent-chat-mcp/.worktrees/go-public-prep/app/be && uv run python -c "import tomllib; tomllib.load(open('pyproject.toml','rb')); print('OK')"
```

Expected: `OK`

**Step 4: Commit**

```bash
cd /Users/tushuyang/agent-chat-mcp/.worktrees/go-public-prep
git add LICENSE app/be/pyproject.toml
git commit -m "chore: add MIT LICENSE and complete pyproject.toml metadata (MCP-1)"
```

---

### Task 2: Code Correctness Blockers (MCP-2)

**Parallel with Tasks 1 and 3 — no interdependencies.**

**Note:** Task 2 also modifies `pyproject.toml`. If Tasks 1 and 2 are executed by separate subagents, they must either coordinate or be merged into one agent's work. In parallel execution, both changes to `pyproject.toml` should be applied in one pass by whoever handles it (combine MCP-1 pyproject.toml changes and MCP-2 fastmcp change together).

**Files:**
- Modify: `app/be/pyproject.toml` — change `fastmcp>=2.0.0` → `fastmcp>=3.0.0`
- Modify: `app/be/agent_chat_mcp/app.py` — change default DB path
- Modify: `app/be/agent_chat_mcp/mcp.py` — change default DB path
- Modify: `CLAUDE.md` — update default path mention in Environment Variables table

**Step 1: Update fastmcp version pin in pyproject.toml**

In `app/be/pyproject.toml`, change:
```
"fastmcp>=2.0.0",
```
to:
```
"fastmcp>=3.0.0",
```

**Step 2: Update default DB path in app.py**

In `app/be/agent_chat_mcp/app.py`, change the `DB_PATH` default:

```python
# Before
DB_PATH = os.path.expanduser(os.environ.get("CHAT_DB_PATH", "~/.claude/agent-chat.db"))

# After
DB_PATH = os.path.expanduser(os.environ.get("CHAT_DB_PATH", "~/.agent-chat/agent-chat.db"))
```

**Step 3: Update default DB path in mcp.py**

In `app/be/agent_chat_mcp/mcp.py`, change the same `DB_PATH` default:

```python
# Before
DB_PATH = os.path.expanduser(os.environ.get("CHAT_DB_PATH", "~/.claude/agent-chat.db"))

# After
DB_PATH = os.path.expanduser(os.environ.get("CHAT_DB_PATH", "~/.agent-chat/agent-chat.db"))
```

**Step 4: Update CLAUDE.md default path**

In `CLAUDE.md`, in the Environment Variables table, change:

```
| `CHAT_DB_PATH` | SQLite database file path | `~/.claude/agent-chat.db` |
```
to:
```
| `CHAT_DB_PATH` | SQLite database file path | `~/.agent-chat/agent-chat.db` |
```

**Step 5: Run tests to confirm nothing broke**

```bash
cd /Users/tushuyang/agent-chat-mcp/.worktrees/go-public-prep/app/be && uv run pytest -x -q
```

Expected: all tests pass (173 tests, tests use in-memory DB so path change has no effect)

**Step 6: Commit**

```bash
cd /Users/tushuyang/agent-chat-mcp/.worktrees/go-public-prep
git add app/be/pyproject.toml app/be/agent_chat_mcp/app.py app/be/agent_chat_mcp/mcp.py CLAUDE.md
git commit -m "fix: pin fastmcp>=3.0.0 and move default DB path out of ~/.claude/ (MCP-2)"
```

---

### Task 3: Scrub Internal References (MCP-3)

**Parallel with Tasks 1 and 2 — no interdependencies.**

**Files:**
- Delete: `docs/skill-migration.md`
- Modify: `.coderabbit.yaml` — replace `team_chat_mcp/` → `agent_chat_mcp/`, remove DESIGN.md path instructions entry
- Modify: `app/be/scripts/import_archive.py` — remove `detect_project()` hardcoded names
- Modify: `SKILL.md` — rename front matter `name: team-chat` → `name: agent-chat`, `aliases: [team-chat]` → `aliases: [agent-chat]`
- Modify: `CLAUDE.md` — remove line 137 (`~/.claude-chan/skills/team-chat/SKILL.md` reference)

**Step 1: Delete docs/skill-migration.md**

```bash
cd /Users/tushuyang/agent-chat-mcp/.worktrees/go-public-prep
rm docs/skill-migration.md
```

This file documents an internal portless/launchd setup specific to the author's machine. Not useful to the public.

**Step 2: Fix .coderabbit.yaml**

Replace all occurrences of `team_chat_mcp/` with `agent_chat_mcp/` in path instructions:
- `app/be/team_chat_mcp/db.py` → `app/be/agent_chat_mcp/db.py`
- `app/be/team_chat_mcp/service.py` → `app/be/agent_chat_mcp/service.py`
- `app/be/team_chat_mcp/mcp.py` → `app/be/agent_chat_mcp/mcp.py`
- `app/be/team_chat_mcp/app.py` → `app/be/agent_chat_mcp/app.py`
- `app/be/team_chat_mcp/routes.py` → `app/be/agent_chat_mcp/routes.py`

Also remove the `DESIGN.md` path instructions block (lines 191–199) — there is no `DESIGN.md` in this project.

Also update `.coderabbit.yaml` line 31: the `## CRITICAL: Documentation Convention` note references `DESIGN.md` — change to:

```yaml
    ## CRITICAL: Documentation Convention
    This project uses CLAUDE.md at the root for documentation.
    Plans live in docs/plans/. Do NOT flag missing README files.
    - PREFER updating existing docs over suggesting new ones
    - Check if CLAUDE.md needs updates based on code changes
```

**Step 3: Genericize import_archive.py detect_project()**

Replace the `detect_project()` function entirely. The function currently maps room name prefixes to internal projects (`runno`, `runno-agent-sdk`, `team-chat-mcp`). For the public release, replace it with a simple generic passthrough — the user must pass `--project` explicitly.

In `app/be/scripts/import_archive.py`:

```python
# Remove detect_project() entirely (lines 31-48)

# Update import_file() to require project as a parameter
# Before: project = detect_project(room_name)
# After: project is passed in from the caller
```

Specifically:
1. Remove the `detect_project()` function (lines 31–48)
2. In `import_file()`, add `project: str` as a required parameter (remove the `detect_project(room_name)` call)
3. In `main()`, add `--project` as a required argument (remove the auto-detect call)
4. Update `main()` to pass `args.project` to `import_file()`

The updated `main()` argument parser should add:
```python
parser.add_argument(
    "--project",
    required=True,
    help="Project name to assign all imported rooms to",
)
```

The updated `import_file()` signature:
```python
def import_file(conn: sqlite3.Connection, filepath: Path, project: str, dry_run: bool = False) -> tuple[int, int]:
```

The updated `main()` call:
```python
imported, skipped = import_file(conn, filepath, project=args.project, dry_run=args.dry_run)
```

**Step 4: Update SKILL.md front matter**

In `SKILL.md`, change lines 1–6:

```yaml
---
name: team-chat
title: team-chat
description: Use when spawning agent teams that need shared discussion visibility beyond hub-and-spoke DMs
aliases: [team-chat]
---
```

to:

```yaml
---
name: agent-chat
title: agent-chat
description: Use when spawning agent teams that need shared discussion visibility beyond hub-and-spoke DMs
aliases: [agent-chat]
---
```

Also update the DB path reference in SKILL.md line 13:
```
**Storage:** SQLite database at `~/.agent-chat/agent-chat.db` (WAL mode). Safe from Claude Code's `TeamDelete`.
```

**Step 5: Clean CLAUDE.md — remove personal skill path reference**

In `CLAUDE.md` (the main CLAUDE.md, not the worktree one), remove the section under "## SKILL.md Dual-Update Rule" that references the personal path:

```
2. Update `~/.claude-chan/skills/team-chat/SKILL.md` (the global skill copy)

Both files must stay in sync. The in-repo `SKILL.md` is the source of truth; copy relevant sections to the global skill after each change.
```

Replace with just:

```
The in-repo `SKILL.md` is the source of truth for MCP tool documentation.
```

The entire "Dual-Update Rule" section refers to an internal personal setup that doesn't apply to the public.

**Step 6: Verify tests still pass**

```bash
cd /Users/tushuyang/agent-chat-mcp/.worktrees/go-public-prep/app/be && uv run pytest -x -q
```

Expected: all tests pass (import_archive.py changes have no backend test coverage but tests are unrelated to this script)

**Step 7: Commit**

```bash
cd /Users/tushuyang/agent-chat-mcp/.worktrees/go-public-prep
git add -A
git commit -m "chore: scrub internal references from configs, docs, and scripts (MCP-3)"
```

---

### Phase 4: Documentation Update

Use /docs-update to update:
- [x] CLAUDE.md updated inline (Steps 2.4 and 3.5 above)
- [x] SKILL.md updated inline (Step 3.4 above)
- [ ] Verify README reflects new default DB path `~/.agent-chat/agent-chat.db`

---

## Verification

After all three tasks complete:

```bash
# 1. Verify LICENSE exists
ls /Users/tushuyang/agent-chat-mcp/.worktrees/go-public-prep/LICENSE

# 2. Verify pyproject.toml parses and has correct metadata
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

# 3. Verify DB path defaults changed
grep -n "agent-chat.db" /Users/tushuyang/agent-chat-mcp/.worktrees/go-public-prep/app/be/agent_chat_mcp/app.py
grep -n "agent-chat.db" /Users/tushuyang/agent-chat-mcp/.worktrees/go-public-prep/app/be/agent_chat_mcp/mcp.py
# Expected: ~/.agent-chat/agent-chat.db (NOT ~/.claude/agent-chat.db)

# 4. Verify no internal refs remain
grep -r "team_chat_mcp" /Users/tushuyang/agent-chat-mcp/.worktrees/go-public-prep/
grep -r "team-chat-mcp\|runno-agent-sdk" /Users/tushuyang/agent-chat-mcp/.worktrees/go-public-prep/app/be/scripts/
grep "team-chat" /Users/tushuyang/agent-chat-mcp/.worktrees/go-public-prep/SKILL.md
# Expected: no matches

# 5. Verify docs/skill-migration.md deleted
ls /Users/tushuyang/agent-chat-mcp/.worktrees/go-public-prep/docs/skill-migration.md 2>&1
# Expected: "No such file or directory"

# 6. Run full test suite
cd /Users/tushuyang/agent-chat-mcp/.worktrees/go-public-prep/app/be && uv run pytest -x -q
```

Expected: LICENSE present, pyproject.toml valid with MIT license + authors + urls + fastmcp>=3.0.0, both DB paths changed, no team_chat_mcp refs, skill-migration.md gone, all 173 tests pass.

## AI Review Findings

[Appended by team discussion]

| Severity | Source | Finding | Action |
|----------|--------|---------|--------|
