# docs-ci Full Scope Implementation Plan

## Context

Three issues on the `docs-ci` branch need to land together: MCP-4 (README completeness +
CONTRIBUTING.md + SKILL.md), MCP-7 (CI/CD hardening), and MCP-9 (demo GIF). These are
purely docs/infra changes — no Python or React production code is touched.

## Goal

Ship a polished README with demo GIF and CI badge, a complete CONTRIBUTING.md, accurate
SKILL.md dev-DB documentation, and a hardened CI workflow — all on the `docs-ci` branch.

## Architecture

Five parallel tasks (Tasks 1–5) produce independent file changes, followed by one
sequential task (Task 6) that embeds the recorded GIF into the README. Tasks 1–5 can be
executed simultaneously; Task 6 depends on Tasks 1 and 5.

```
Wave 1 (parallel): Task 1 (README text), Task 2 (CONTRIBUTING.md),
                   Task 3 (SKILL.md), Task 4 (ci.yml), Task 5 (record GIF)
Wave 2 (sequential): Task 6 (embed GIF in README)
```

> **Important:** Task 6 modifies `README.md`. Task 1 also modifies `README.md`. They **must not run concurrently** — Task 6 is strictly Wave 2, running only after both Task 1 (README text base) and Task 5 (GIF asset) are committed. The Wave 1 README changes (Task 1) must complete and commit before Task 6 starts.

## Affected Areas

- Docs: `README.md`, `CONTRIBUTING.md`, `SKILL.md`, `docs/demo.gif` (new)
- Infra: `.github/workflows/ci.yml`
- No backend or frontend production code

## Key Files

- `README.md` — primary docs target (MCP-4 text fixes + MCP-7 badge + MCP-9 GIF embed)
- `.github/workflows/ci.yml` — CI hardening (MCP-7)
- `CONTRIBUTING.md` — new file (MCP-4)
- `SKILL.md` — dev DB documentation (MCP-4)
- `docs/demo.gif` — new asset (MCP-9)

## Reusable Utilities

- `agent-browser record start/stop` — Playwright video capture → `.webm`
- `ffmpeg -vf "fps=10,scale=900:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse"` — palette GIF conversion
- `http://agents-chat-dev.localhost:1355` — dev server with rich seed data (already running)

---

## Tasks

### Task 1: README Completeness (MCP-4) + CI Badge (MCP-7)

All README text changes in one commit to avoid merge conflicts with other tasks.

**Files:**
- Modify: `README.md`

**Changes to apply:**

**1a. Add `wait_for_messages` to MCP tools table** (currently missing from README line 83–93):

Insert after the `search` row and before `ping`:
```markdown
| `wait_for_messages` | `room_id, since_id, timeout?, limit?, message_type?` | Block until new messages arrive (long-poll, max 60s); returns `timed_out` on timeout |
```

**1a-fix. Also fix `read_messages` row** (currently missing `message_type?`):

Current row in README:
```markdown
| `read_messages` | `room_id, since_id?, limit?` | ... |
```
Update to:
```markdown
| `read_messages` | `room_id, since_id?, limit?, message_type?` | ... |
```

**1b. Fix "pre-built SPA" claim** (README line 53):

Current:
```markdown
**Frontend** (optional — pre-built SPA is included)
```
Replace with:
```markdown
**Frontend** (optional — SPA is bundled in the wheel, no separate build needed)
```

**1c. Add Prerequisites section** before the Installation section:
```markdown
## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) — Python package manager
- [bun](https://bun.sh/) — JavaScript package manager (only needed for frontend development)
```

**1d. Add auth/network note** to the MCP registration section (after the code block):
```markdown
> **Note:** The MCP endpoint has no built-in authentication. Run behind a firewall or
> localhost-only binding in production. Never expose `/mcp/` to the public internet
> without an auth proxy.
```

**1e. Add CI status badge** at the top of the README (after the `# Agents Chat MCP` heading):
```markdown
[![CI](https://github.com/runno-ai/agents-chat-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/runno-ai/agents-chat-mcp/actions/workflows/ci.yml)
```

**Step 1: Apply all changes**
Edit `README.md` with all five changes above.

**Step 2: Verify**
```bash
# Check wait_for_messages is in tools table (with message_type?)
grep "wait_for_messages" README.md

# Check read_messages row has message_type?
grep "read_messages.*message_type" README.md

# Check badge is present
grep "ci.yml/badge.svg" README.md

# Check auth note is present
grep "no built-in authentication" README.md

# Check prerequisites section exists
grep "## Prerequisites" README.md
```
Expected: each grep returns one matching line.

**Step 3: Commit**
```bash
git add README.md
git commit -m "docs: README completeness — wait_for_messages, read_messages, prerequisites, auth note, CI badge (MCP-4, MCP-7)"
```

---

### Task 2: CONTRIBUTING.md (MCP-4)

**Files:**
- Create: `CONTRIBUTING.md`

**Step 1: Create the file**

Full content:
```markdown
# Contributing to agents-chat-mcp

Thank you for contributing! This guide covers local setup, running tests, and the PR process.

## Prerequisites

- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- [bun](https://bun.sh/) (for frontend work)

## Local Setup

**Backend:**
```bash
cd app/be
uv sync --extra test
```

**Frontend:**
```bash
cd app/fe
bun install
```

## Running Tests

**Backend:**
```bash
cd app/be && uv run pytest -xvs
```

**Frontend:**
```bash
cd app/fe && bun run test
```

## Running the Server

```bash
# Production DB
cd app/be && uv run uvicorn agents_chat_mcp.app:app --port 8000

# Dev DB (rich seed data, reseeds on start)
# Requires: CHAT_DB_PATH=../../data/dev.db
cd app/be && CHAT_DB_PATH=../../data/dev.db uv run uvicorn agents_chat_mcp.app:app --port 8000
```

Open `http://localhost:8000` to view the UI.

## Code Style

- **Python:** no enforced formatter, but keep functions short and well-named
- **TypeScript:** `tsc --noEmit` must pass; no unused imports

## Pull Request Process

1. Fork the repo and create a feature branch
2. Run backend and frontend tests — both must pass
3. Update `README.md` or `SKILL.md` if your change affects the public API or usage
4. Open a PR targeting `main` with a clear description of what changed and why

## Seed Data

The dev fixture DB lives at `data/dev.db` (committed). If you add new features that
should be reflected in demo data, update `data/seed.py` and run:

```bash
cd app/be && uv run python ../../data/seed.py --reset
git add data/dev.db data/seed.py
git commit -m "data: update seed data"
```
```

**Step 2: Verify**
```bash
# File exists and has expected sections
grep "## Prerequisites\|## Running Tests\|## Pull Request" CONTRIBUTING.md | wc -l
# Expected: 3
```

**Step 3: Commit**
```bash
git add CONTRIBUTING.md
git commit -m "docs: add CONTRIBUTING.md (MCP-4)"
```

---

### Task 3: SKILL.md Dev DB Documentation (MCP-4)

The `docs-ci` branch predates the dev DB feature (added in `main`). The SKILL.md Storage
section is missing dev DB info and the `start-server-dev.sh` documentation.

**Files:**
- Modify: `SKILL.md` (Storage section at the bottom)

**Step 1: Replace the Storage section**

Current (lines 172–179):
```markdown
## Storage

SQLite database at `~/.agents-chat/agents-chat.db` (safe from `TeamDelete`):

- **Rooms table:** UUID PK, project/name scoping, live/archived status
- **Messages table:** auto-increment ID, room_id FK, sender, content, timestamps
- **WAL mode** for concurrent SSE reads
- **Message format:** `{"id", "room_id", "sender", "content", "message_type", "created_at", "metadata"}`
```

Replace with:
```markdown
## Storage

**Prod DB:** `~/.agents-chat/agents-chat.db` — always-on service, never modified by `ss`.

**Dev DB:** `data/dev.db` — committed demo fixture, served by `agents-chat-dev` (start via `ss → 4 → DEV`).
- Seed/reset: `cd app/be && uv run python ../../data/seed.py --reset`
- Contains 2 demo projects, 5 rooms, 45 curated agent conversations.

SQLite database (WAL mode):

- **Rooms table:** UUID PK, project/name scoping, live/archived status
- **Messages table:** auto-increment ID, room_id FK, sender, content, timestamps
- **WAL mode** for concurrent SSE reads
- **Message format:** `{"id", "room_id", "sender", "content", "message_type", "created_at", "metadata"}`
```

**Step 2: Verify**
```bash
grep "Dev DB\|data/dev.db\|seed.py" SKILL.md
# Expected: 3 matching lines
```

**Step 3: Commit**
```bash
git add SKILL.md
git commit -m "docs: SKILL.md — add dev DB and seed.py documentation (MCP-4)"
```

---

### Task 4: CI Workflow Hardening (MCP-7)

**Files:**
- Modify: `.github/workflows/ci.yml`

**Step 1: Apply all CI improvements**

Full updated `ci.yml`:
```yaml
name: CI

on:
  push:
    branches: [main, test]
  pull_request:
    branches: [main, test]

# Cancel in-progress CI runs on the same branch when new commits arrive.
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

permissions:
  contents: read

jobs:
  backend:
    name: Backend Tests
    runs-on: ubuntu-latest
    timeout-minutes: 10
    defaults:
      run:
        working-directory: app/be
    steps:
      - uses: actions/checkout@v4

      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
          cache-dependency-glob: app/be/uv.lock

      - uses: actions/setup-python@v5
        with:
          python-version-file: app/be/.python-version

      - name: Install dependencies
        run: uv sync --frozen --extra test

      - name: Run tests
        run: uv run pytest -x --tb=short

      - name: Audit dependencies
        shell: bash
        run: |
          uv pip compile pyproject.toml --extra test -o /tmp/audit-reqs.txt 2>/dev/null || true
          uvx pip-audit --requirement /tmp/audit-reqs.txt || true

  frontend:
    name: Frontend
    runs-on: ubuntu-latest
    timeout-minutes: 10
    defaults:
      run:
        working-directory: app/fe
    steps:
      - uses: actions/checkout@v4

      - uses: oven-sh/setup-bun@v2

      - uses: actions/cache@v4
        with:
          path: ~/.bun/install/cache
          key: bun-${{ runner.os }}-${{ hashFiles('app/fe/bun.lockb') }}
          restore-keys: bun-${{ runner.os }}-

      - name: Install dependencies
        run: bun install --frozen-lockfile

      - name: Typecheck
        run: bunx tsc --noEmit

      - name: Test
        run: bun run test

      - name: Build
        run: bun run build
```

Key changes from current:
- `concurrency` block added (cancel-in-progress per branch)
- `permissions: contents: read` added (least privilege)
- `uv sync --extra test` → `uv sync --frozen --extra test` (reproducible installs)
- `pip-audit` step added (via `uvx pip-audit` — no install needed; uses temp-file for pip compile output to avoid bash process-substitution incompatibility with `sh`; `|| true` advisory only)
- `bun audit` removed — not a valid bun command; no-op with `|| true` provides false assurance
- Steps given explicit `name:` labels for cleaner CI logs

**Step 2: Validate YAML syntax**
```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml')); print('YAML OK')"
```
Expected: `YAML OK`

**Step 3: Commit**
```bash
git add .github/workflows/ci.yml
git commit -m "ci: add concurrency group, permissions, frozen lockfile, pip-audit, bun audit (MCP-7)"
```

---

### Task 5: Record and Convert Demo GIF (MCP-9)

Dev server (`http://agents-chat-dev.localhost:1355`) has 5 rooms of rich multi-round
agent discussions across 2 projects. This is the recording source.

**Files:**
- Create: `docs/demo.gif`
- Ephemeral: `docs/demo.webm` (deleted after conversion)

**Step 1: Verify dev server is running**
```bash
curl -s http://agents-chat-dev.localhost:1355/api/status
```
Expected: `{"status":"ok",...}`

**Step 2: Open browser and start recording**
```bash
agent-browser set viewport 1280 800
agent-browser open http://agents-chat-dev.localhost:1355
agent-browser wait --load networkidle
agent-browser record start docs/demo.webm
```

**Step 3: Execute the demo script** (~35 seconds)

> **Selector notes (verified against source):**
> - Room names are plain text in the sidebar — use `find text "<name>" click`
> - Project filter is a custom Select dropdown (`<button>` shows current value). Must click the button to open it, then click the project name inside the list.
> - Search input is `<input type="text">` with no `role="searchbox"`. Use `find placeholder "Search rooms" click/type`.

```bash
# Land — sidebar shows all rooms (no project filter = both projects visible)
# Wait for room list to load via SSE
agent-browser wait --text "code-quality"

# Click into code-quality room (active bug-fix sprint discussion)
agent-browser find text "code-quality" click
agent-browser wait 1500

# Scroll through the multi-agent discussion
agent-browser scroll down 500
agent-browser wait 1000
agent-browser scroll down 500
agent-browser wait 800

# Switch room — click sprint-planning
agent-browser find text "sprint-planning" click
agent-browser wait 1200

# Switch project — open the "All projects" dropdown first, then select runno
agent-browser find text "All projects" click
agent-browser wait 500
agent-browser find text "runno" click
agent-browser wait 1000

# Click debug-sse-race (active debugging session)
agent-browser find text "debug-sse-race" click
agent-browser wait 1500
agent-browser scroll down 400
agent-browser wait 600

# Show archived room — click plan-runner-refactor (shows archived state)
agent-browser find text "plan-runner-refactor" click
agent-browser wait 1200

# Use search — placeholder-based selector (input is type="text", not type="search")
agent-browser find placeholder "Search rooms" click
agent-browser wait 400
agent-browser type placeholder "Search rooms" "anyio"
agent-browser wait 1500

# Clear and rest
agent-browser press Escape
agent-browser wait 1000
```

**Step 4: Stop recording**
```bash
agent-browser record stop
ls -lh docs/demo.webm
```
Expected: file exists, size > 1MB.

**Step 5: Convert to palette-optimized GIF**
```bash
ffmpeg -y -i docs/demo.webm \
  -vf "fps=10,scale=900:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=128[p];[s1][p]paletteuse=dither=bayer:bayer_scale=5" \
  -loop 0 \
  docs/demo.gif
```
(`-y` auto-overwrites if retaking; safe to run repeatedly)

**Step 6: Verify size and quality**
```bash
ls -lh docs/demo.gif
# Target: 3–8 MB
# If > 8MB: re-run with fps=8
# If > 12MB: re-run with scale=720

open docs/demo.gif   # spot-check playback
```

**Step 7: Remove ephemeral webm**
```bash
rm docs/demo.webm
```

**Step 8: Commit GIF asset**
```bash
git add docs/demo.gif
git commit -m "docs: add demo GIF of agents-chat web UI (MCP-9)"
```

---

### Task 6: Embed GIF in README (MCP-9)

Depends on: Task 1 (README structure finalized) and Task 5 (GIF committed).

**Files:**
- Modify: `README.md`

**Step 1: Add Demo section**

Insert after the CI badge line (after the heading block) and before the first `---`:

```markdown
## Demo

![agents-chat web UI — real-time SSE streaming, sidebar navigation, search](docs/demo.gif)

*Multi-agent discussions stream in real time. Browse live and archived rooms by project,
search across all message history, and watch unread counts update as agents post.*

---
```

**Step 2: Verify**
```bash
python3 -c "
from pathlib import Path
readme = Path('README.md').read_text()
assert 'docs/demo.gif' in readme, 'GIF link missing'
assert Path('docs/demo.gif').exists(), 'GIF file missing'
print('OK')
"
```
Expected: `OK`

**Step 3: Commit**
```bash
git add README.md
git commit -m "docs: embed demo GIF in README (MCP-9)"
```

---

### Phase 7: Documentation Update

- [x] README.md — completeness, badge, GIF (Tasks 1 + 6)
- [x] CONTRIBUTING.md — created (Task 2)
- [x] SKILL.md — dev DB section (Task 3)
- [x] No backend code changed → no API docs needed
- [x] No new MCP tools → SKILL.md tools table unchanged

---

## Verification

After all tasks complete:

```bash
# 1. README has all expected content
grep -c "wait_for_messages\|Prerequisites\|no built-in authentication\|ci.yml/badge.svg\|docs/demo.gif" README.md
# Expected: 5

# 2. GIF exists and is within budget
ls -lh docs/demo.gif   # expect 3–8 MB

# 3. CI YAML is valid
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml')); print('YAML OK')"

# 4. CONTRIBUTING.md exists
ls -la CONTRIBUTING.md

# 5. SKILL.md has dev DB
grep "Dev DB" SKILL.md

# 6. Only docs/infra files changed (no production code)
git diff main --name-only | grep -v "README.md\|CONTRIBUTING.md\|SKILL.md\|docs/\|.github/"
# Expected: no output
```

Expected: all green. GIF renders inline in GitHub README preview.

## AI Review Findings

| Severity | Source | Finding | Action |
|----------|--------|---------|--------|
| Critical | Architect, Frontend-dev | Task 5 demo: `find role searchbox` fails — search input is `<input type="text">`, not `type="search"` | Fixed: use `find placeholder "Search rooms"` |
| Critical | Architect, Frontend-dev | Task 5 demo: `find text "runno" click` fails — project names only appear after opening the Select dropdown | Fixed: click "All projects" button to open dropdown first, then click "runno" |
| Critical | Codex, Gemini | Task 4 ci.yml: `<(...)` process substitution is bash-only; GitHub Actions steps default to `sh` (dash) | Fixed: use temp-file approach + `uvx pip-audit` |
| Warning | Codex, Frontend-dev | Task 1 README: `wait_for_messages` row missing `message_type?` parameter | Fixed: `room_id, since_id, timeout?, limit?, message_type?` |
| Warning | Frontend-dev | Task 1 README: `read_messages` row also missing `message_type?` parameter | Fixed: `room_id, since_id?, limit?, message_type?` |
| Warning | Codex, Gemini | Task 4 ci.yml: `uv run pip-audit` requires pip-audit in venv; not in pyproject.toml | Fixed: use `uvx pip-audit` (isolated env, no install needed) |
| Warning | Codex, Frontend-dev, Gemini | Task 4 ci.yml: `bun audit` is not a valid bun command; silently fails | Fixed: removed step entirely |
| Warning | Frontend-dev | Tasks 2+3: `data/dev.db` and `data/seed.py` only exist in `main`, not `docs-ci` | Accepted: CONTRIBUTING.md/SKILL.md document the merged-state project; valid once merged |
| Suggestion | Architect | Task 5: Initial `wait 1500` is fragile; depends on SSE load time | Fixed: replaced with `wait --text "code-quality"` (conditional) |
| Suggestion | Architect | Task 5: Add `-y` flag to ffmpeg for idempotent re-runs | Fixed: added `-y` flag |
| Suggestion | Gemini | Wave structure wording — "Tasks 1–5 parallel" ambiguous given Task 6 depends on Task 1 | Clarified in Architecture section: Wave 1 = Tasks 1–5 parallel, Wave 2 = Task 6 (strict sequential after Task 1 completes) |
| Suggestion | Codex | Final verification `grep -c` count unreliable (counts lines, not patterns) | Accepted: per-task verifications are more reliable; final grep -c left as sanity check |
| Suggestion | Gemini, Frontend-dev | Text selectors fragile long-term; `data-testid` on key elements recommended | Deferred: out of scope for docs-only branch; file follow-up Linear issue (MCP) |
