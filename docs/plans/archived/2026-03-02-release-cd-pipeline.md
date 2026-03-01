# Release & CD Pipeline Implementation Plan

## Context

agent-chat-mcp currently has CI (tests on push to `main`) but no CD pipeline, no PyPI publishing,
and no defined release process. MCP-10 introduces a `test` staging branch, automated pre-release
publishing on push to `test`, and stable publishing on push to `main`, with the React frontend
bundled into the Python wheel.

## Goal

Automate PyPI pre-release (on `test`) and stable (on `main`) publishing via GitHub Actions with
the frontend SPA bundled into the wheel, using OIDC Trusted Publishing (no stored secrets).

## Architecture

- **Frontend bundling:** Build step copies `app/fe/dist/index.html` into
  `app/be/agent_chat_mcp/static/` before `uv build`. hatchling auto-includes everything under
  the package directory, so the frontend ships in the wheel. Note: `vite-plugin-singlefile`
  inlines all JS/CSS into a single `index.html` — no separate asset chunks to copy.
- **Static dir default:** `app.py` extracts `_default_static_dir()` function returning
  `Path(__file__).parent / "static"`. Tested directly (no `importlib.reload`). Env var override
  still works for local dev.
- **Version source of truth:** `pyproject.toml`. No `package.json` sync needed (`private: true`,
  never published to npm).
- **Pre-release versioning:** `{pyproject_version}rc{github.run_number}` — PEP 440 compliant.
- **Stable versioning:** `{pyproject_version}` as-is from pyproject.toml.
- **CD trigger:** `push` to `test` or `main`. Test jobs removed from cd.yml — branch protection
  on `test`/`main` requires CI to pass before merge, so tests run exactly once per push.
- **Publishing:** PyPI OIDC Trusted Publishing (`id-token: write`) — no stored secrets.
- **Idempotent tagging:** Check tag existence before creating to survive CD reruns.

## Affected Areas

- Backend: `app/be/agent_chat_mcp/app.py`, `app/be/pyproject.toml`
- CI/CD: `.github/workflows/ci.yml` (extend triggers), `.github/workflows/cd.yml` (new)
- Tests: `app/be/tests/test_app_config.py` (new)
- Docs: `RELEASING.md` (new)
- Skills: `~/.claude-chan/skills/deployment/SKILL.md` (new)

## Key Files

- `app/be/pyproject.toml` — version source of truth + hatchling build config
- `app/be/agent_chat_mcp/app.py` — STATIC_DIR refactor (line 26)
- `.github/workflows/ci.yml` — add `test` branch triggers
- `.github/workflows/cd.yml` — new CD workflow (pre-release + stable, OIDC auth)
- `app/be/tests/test_app_config.py` — new config test

## Reusable Utilities

- `.github/workflows/ci.yml:backend` job — pattern copied for CD publish job structure
- `app/be/agent_chat_mcp/app.py:STATIC_DIR` — extract to function, refactor default
- `astral-sh/setup-uv@v5` — reuse existing `enable-cache`/`cache-dependency-glob` pattern

---

## Tasks

### Task 1: Refactor STATIC_DIR to use package-internal path

**Files:**
- Modify: `app/be/agent_chat_mcp/app.py:26`
- Create: `app/be/agent_chat_mcp/static/.gitkeep`
- Create: `app/be/tests/test_app_config.py`

**Step 1: Write the failing test**

```python
# app/be/tests/test_app_config.py
"""Test STATIC_DIR default resolves to package-internal static/ directory."""
from pathlib import Path


def test_default_static_dir_is_package_relative():
    """_default_static_dir() returns the package-internal static/ path."""
    import agent_chat_mcp.app as m

    result = m._default_static_dir()
    expected = str(Path(m.__file__).parent / "static")
    assert result == expected, (
        f"Expected package-relative static dir {expected!r}, got {result!r}"
    )
```

**Step 2: Run test — expect FAIL**

```bash
cd app/be && uv run pytest tests/test_app_config.py -xvs
```

Expected: `AttributeError: module 'agent_chat_mcp.app' has no attribute '_default_static_dir'`

**Step 3: Implement minimal code**

In `app/be/agent_chat_mcp/app.py`, replace line 26:

```python
# Before:
STATIC_DIR = os.environ.get("STATIC_DIR", os.path.join(os.path.dirname(__file__), "../../fe/dist"))

# After (add Path import at top of imports, replace the line):
from pathlib import Path


def _default_static_dir() -> str:
    """Return the package-internal static/ directory path."""
    return str(Path(__file__).parent / "static")


STATIC_DIR = os.environ.get("STATIC_DIR", _default_static_dir())
```

Also create the static directory placeholder:

```bash
mkdir -p app/be/agent_chat_mcp/static
touch app/be/agent_chat_mcp/static/.gitkeep
```

**Step 4: Run test — expect PASS**

```bash
cd app/be && uv run pytest tests/test_app_config.py -xvs
```

Expected: `1 passed`

**Step 5: Run full backend tests to confirm no regressions**

```bash
cd app/be && uv run pytest -x --tb=short
```

**Step 6: Commit**

```bash
git add app/be/agent_chat_mcp/app.py \
        app/be/agent_chat_mcp/static/.gitkeep \
        app/be/tests/test_app_config.py
git commit -m "fix: use package-internal static/ dir as STATIC_DIR default

Extracts _default_static_dir() function returning Path(__file__).parent/static.
This is the correct path for PyPI installs where the frontend is bundled
into the wheel. Env var override (STATIC_DIR) still works for local dev.

Refs: MCP-10"
```

---

### Task 2: Update CI — add `test` branch triggers

**Files:**
- Modify: `.github/workflows/ci.yml`

**Step 1: Update ci.yml triggers**

Replace the `on:` block with:

```yaml
on:
  push:
    branches: [main, test]
  pull_request:
    branches: [main, test]
```

Full updated file:

```yaml
name: CI

on:
  push:
    branches: [main, test]
  pull_request:
    branches: [main, test]

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

      - run: uv sync --extra test

      - run: uv run pytest -x --tb=short

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

      - run: bun install --frozen-lockfile

      - name: Typecheck
        run: bunx tsc --noEmit

      - name: Test
        run: bun run test

      - name: Build
        run: bun run build
```

**Step 2: Validate YAML**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))" && echo "ci.yml: valid"
```

Expected: `ci.yml: valid`

**Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: run tests on test branch push/PR

Extends CI triggers to include the test staging branch so that
PRs targeting test are validated before merge.

Refs: MCP-10"
```

---

### Task 3: Create CD workflow

**Files:**
- Create: `.github/workflows/cd.yml`

Note: CD has no test jobs — branch protection on `test` and `main` requires CI to pass before
merge, so tests run exactly once per push (not duplicated). CD exclusively handles build +
publish. Publish uses OIDC Trusted Publishing (no `PYPI_TOKEN` stored as secret; requires
one-time Trusted Publisher setup in PyPI project settings — see RELEASING.md).

**Step 1: Create `.github/workflows/cd.yml`**

```yaml
name: CD

on:
  push:
    branches: [test, main]
  workflow_dispatch:
    inputs:
      branch:
        description: "Branch to publish from (test or main)"
        required: true
        default: test

jobs:
  publish:
    name: Build & Publish
    runs-on: ubuntu-latest
    permissions:
      contents: write    # For creating tags and GitHub Releases
      id-token: write    # For OIDC Trusted Publishing to PyPI
    steps:
      - uses: actions/checkout@v4

      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
          cache-dependency-glob: app/be/uv.lock

      - uses: actions/setup-python@v5
        with:
          python-version-file: app/be/.python-version

      - uses: oven-sh/setup-bun@v2

      - uses: actions/cache@v4
        with:
          path: ~/.bun/install/cache
          key: bun-${{ runner.os }}-${{ hashFiles('app/fe/bun.lockb') }}
          restore-keys: bun-${{ runner.os }}-

      # ── Determine version ──────────────────────────────────────────────
      - name: Read base version from pyproject.toml
        id: base_version
        run: |
          VERSION=$(python3 -c "
          import tomllib
          with open('app/be/pyproject.toml', 'rb') as f:
              data = tomllib.load(f)
          print(data['project']['version'])
          ")
          echo "version=$VERSION" >> "$GITHUB_OUTPUT"

      - name: Compute publish version
        id: version
        run: |
          BASE="${{ steps.base_version.outputs.version }}"
          if [[ "${{ github.ref }}" == "refs/heads/test" ]]; then
            PUBLISH_VERSION="${BASE}rc${{ github.run_number }}"
            IS_PRERELEASE=true
          else
            PUBLISH_VERSION="${BASE}"
            IS_PRERELEASE=false
          fi
          echo "publish_version=$PUBLISH_VERSION" >> "$GITHUB_OUTPUT"
          echo "is_prerelease=$IS_PRERELEASE" >> "$GITHUB_OUTPUT"
          echo "Publishing version: $PUBLISH_VERSION (prerelease=$IS_PRERELEASE)"

      # ── Build frontend ─────────────────────────────────────────────────
      - name: Install frontend deps
        working-directory: app/fe
        run: bun install --frozen-lockfile

      - name: Build frontend
        working-directory: app/fe
        run: bun run build

      # ── Bundle frontend into Python package ───────────────────────────
      - name: Bundle frontend into package
        run: |
          mkdir -p app/be/agent_chat_mcp/static
          cp app/fe/dist/index.html app/be/agent_chat_mcp/static/index.html
          echo "Bundled frontend:"
          ls -lh app/be/agent_chat_mcp/static/

      # ── Set pre-release version in pyproject.toml (test branch only) ──
      - name: Set pre-release version in pyproject.toml
        if: github.ref == 'refs/heads/test'
        run: |
          # Note: regex rewrite is safe here — pyproject.toml format is stable
          # and under our control. tomli-w not used to avoid adding a dep.
          python3 -c "
          import pathlib, re
          p = pathlib.Path('app/be/pyproject.toml')
          content = p.read_text()
          new_content = re.sub(
              r'^version = \"[^\"]+\"',
              'version = \"${{ steps.version.outputs.publish_version }}\"',
              content,
              flags=re.MULTILINE
          )
          p.write_text(new_content)
          print('Set version to ${{ steps.version.outputs.publish_version }}')
          "

      # ── Build Python wheel ─────────────────────────────────────────────
      - name: Build wheel
        working-directory: app/be
        run: uv build

      # ── Verify frontend is bundled in wheel ───────────────────────────
      - name: Verify wheel contains frontend
        working-directory: app/be
        run: |
          python3 -c "
          import zipfile, glob
          wheel = sorted(glob.glob('dist/*.whl'))[-1]
          with zipfile.ZipFile(wheel) as z:
              names = z.namelist()
              static_files = [n for n in names if 'static' in n]
              print('Static files in wheel:', static_files)
              assert any('index.html' in n for n in static_files), \
                  'FAIL: index.html missing from wheel!'
              print('OK: frontend bundled in wheel')
          "

      # ── Publish to PyPI via OIDC Trusted Publishing ────────────────────
      - name: Publish to PyPI
        working-directory: app/be
        run: uv publish --trusted-publishing always

      # ── Create tag + GitHub Release ────────────────────────────────────
      - name: Create tag and GitHub Release
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          VERSION="${{ steps.version.outputs.publish_version }}"
          TAG="v${VERSION}"
          IS_PRERELEASE="${{ steps.version.outputs.is_prerelease }}"

          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"

          # Idempotent: skip tag creation if already exists (handles CD reruns)
          if git tag -l "$TAG" | grep -q "$TAG"; then
            echo "Tag $TAG already exists — skipping tag creation"
          else
            git tag -a "$TAG" -m "Release $TAG"
            git push origin "$TAG"
          fi

          # Create release only if it doesn't exist
          if gh release view "$TAG" &>/dev/null; then
            echo "Release $TAG already exists — skipping"
          else
            PRERELEASE_FLAG=""
            [[ "$IS_PRERELEASE" == "true" ]] && PRERELEASE_FLAG="--prerelease"
            gh release create "$TAG" \
              --title "Release $TAG" \
              --generate-notes \
              --verify-tag \
              $PRERELEASE_FLAG
          fi
```

**Step 2: Validate YAML**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/cd.yml'))" && echo "cd.yml: valid"
```

Expected: `cd.yml: valid`

**Step 3: Commit**

```bash
git add .github/workflows/cd.yml
git commit -m "feat(cd): add CD workflow for pre-release and stable publishing

On push to test: publish {version}rc{run_number} pre-release to PyPI.
On push to main: publish stable {version} to PyPI + tag + GitHub Release.
Uses OIDC Trusted Publishing (no stored PYPI_TOKEN secret).
Frontend bundled into agent_chat_mcp/static/ before uv build.
Tag and release steps are idempotent (safe to rerun on partial failure).
No test jobs in CD — branch protection enforces CI pass before merge.

Requires one-time Trusted Publisher setup in PyPI project settings.
See RELEASING.md for instructions.

Refs: MCP-10"
```

---

### Task 4: RELEASING.md

**Files:**
- Create: `RELEASING.md`

**Step 1: Create RELEASING.md**

```markdown
# Releasing agent-chat-mcp

## Branching Model

```
dev/* (feature branches)
  └─► test (staging / pre-release)
         └─► main (production / stable)
```

- **Feature work** happens on `dev/*` or short-lived branches.
- **Merge to `test`** → triggers a pre-release publish (`{version}rc{run_number}` to PyPI).
- **Merge to `main`** → triggers a stable publish (`{version}` to PyPI + GitHub Release).
- **Branch protection** on both `test` and `main` requires CI to pass before merge.

## One-Time Setup: PyPI Trusted Publisher

The CD workflow uses OIDC Trusted Publishing — no stored secrets needed.

Configure once in PyPI project settings:

1. Go to https://pypi.org/manage/project/agent-chat-mcp/settings/publishing/
2. Add a new Trusted Publisher with:
   - **Owner:** `runno-ai`
   - **Repository:** `agent-chat-mcp`
   - **Workflow filename:** `cd.yml`
   - **Environment:** _(leave blank)_
3. Save. No GitHub secret needed.

## Release Checklist

### Pre-release (merge to `test`)

1. Ensure your branch passes CI (push or open a PR targeting `test`).
2. Merge when approved.
3. CD pipeline triggers automatically:
   - Builds and bundles frontend into the wheel
   - Publishes `{version}rc{run_number}` to PyPI (pre-release)
   - Creates GitHub pre-release with auto-generated notes
4. Verify: `pip install agent-chat-mcp --pre`

### Stable release (merge `test` → `main`)

1. **Bump version in `app/be/pyproject.toml`:**
   ```toml
   version = "0.3.0"
   ```
2. Commit: `git commit -m "chore: bump version to 0.3.0"`
3. Push to `test` first to verify a pre-release builds cleanly.
4. Open a PR from `test` → `main`, merge when approved.
5. CD pipeline triggers automatically:
   - Publishes `0.3.0` stable to PyPI
   - Tags `v0.3.0`
   - Creates GitHub Release with auto-generated changelog

### Version bump timing

Version is bumped on the `test` branch **before** opening the `test` → `main` PR.
This ensures the stable release uses the intended version.

### Verify the release

```bash
# Check PyPI
pip install agent-chat-mcp==0.3.0

# Check GitHub Releases
gh release list --repo runno-ai/agent-chat-mcp
```

## Monitoring Deployments

```bash
# Recent CD runs
gh run list --workflow=cd.yml --repo runno-ai/agent-chat-mcp --limit 5

# Latest run details
gh run view --repo runno-ai/agent-chat-mcp

# Trigger manual CD run (workflow_dispatch)
gh workflow run cd.yml --repo runno-ai/agent-chat-mcp --ref test
```

Or use the `/deployment` Claude skill:
```
/deployment status
/deployment logs
/deployment trigger
```

## Conventional Commits

Use these prefixes for clean auto-generated release notes:

| Prefix | Meaning |
|--------|---------|
| `feat:` | New feature |
| `fix:` | Bug fix |
| `chore:` | Maintenance |
| `docs:` | Documentation |
| `ci:` | CI/CD changes |
| `refactor:` | Refactoring |
```

**Step 2: Commit**

```bash
git add RELEASING.md
git commit -m "docs: add RELEASING.md with branching model and release checklist

Documents test→main branching strategy, PyPI OIDC Trusted Publisher
setup, release steps, version bump timing, and monitoring commands.

Refs: MCP-10"
```

---

### Task 5: /deployment Skill

**Files:**
- Create: `~/.claude-chan/skills/deployment/SKILL.md`

Note: Skill definition — no tests. Create directory and file on local machine.

**Step 1: Create the deployment skill**

```bash
mkdir -p ~/.claude-chan/skills/deployment
```

File content for `~/.claude-chan/skills/deployment/SKILL.md`:

```markdown
# Deployment Skill

Use when monitoring or triggering the agent-chat-mcp CD pipeline. Checks workflow
status, shows recent runs, and can trigger manual workflow dispatch.

## Usage

```
/deployment            → show recent CD runs
/deployment status     → show latest run status
/deployment logs       → show logs for latest CD run
/deployment trigger    → manually dispatch CD workflow on current branch
```

## Behavior

### `/deployment` (no args) or `/deployment status`

```bash
gh run list --workflow=cd.yml --repo runno-ai/agent-chat-mcp --limit 5 \
  --json status,conclusion,headBranch,displayTitle,createdAt,url \
  | python3 -m json.tool
```

Display as a table: branch, status, conclusion, created_at, URL.

### `/deployment logs`

```bash
RUN_ID=$(gh run list --workflow=cd.yml --repo runno-ai/agent-chat-mcp --limit 1 \
  --json databaseId --jq '.[0].databaseId')
gh run view "$RUN_ID" --repo runno-ai/agent-chat-mcp --log
```

### `/deployment trigger`

```bash
BRANCH=$(git branch --show-current)
# Confirm with user, then:
gh workflow run cd.yml --repo runno-ai/agent-chat-mcp \
  --ref "$BRANCH" \
  --field branch="$BRANCH"
echo "CD workflow triggered on $BRANCH"
```

## Output Format

Report for each run:
- Status (queued / in_progress / completed)
- Conclusion (success / failure / cancelled)
- Branch and version being published
- Link to run URL
- Time since triggered
```

**Step 2: Verify skill file exists**

```bash
ls -la ~/.claude-chan/skills/deployment/SKILL.md
```

Expected: file exists with non-zero size.

**Step 3: Commit repo changes only**

```bash
# Skill file is local (~/.claude-chan/) — not in the repo
# Commit any remaining repo-tracked changes
git status
git commit -m "feat(skill): add /deployment skill for CD pipeline monitoring

~/.claude-chan/skills/deployment/SKILL.md provides /deployment status,
/deployment logs, /deployment trigger for monitoring the CD pipeline.

Refs: MCP-10" --allow-empty
```

---

### Phase 6: Documentation Update

- [ ] Update `README.md` — add "Installation from PyPI" section
- [ ] Update `CLAUDE.md` — note CD workflow, Trusted Publisher requirement
- [ ] No docstrings needed (only STATIC_DIR one-liner changed)
- [ ] No API docs changes (no endpoint changes)

---

## Verification

After all tasks complete:

```bash
# 1. Backend tests pass (including new config test)
cd app/be && uv run pytest -x --tb=short
# Expected: all tests pass including test_app_config.py

# 2. Frontend builds cleanly
cd app/fe && bun run build
# Expected: dist/index.html created

# 3. Manual bundle step works
mkdir -p app/be/agent_chat_mcp/static
cp app/fe/dist/index.html app/be/agent_chat_mcp/static/index.html
ls -lh app/be/agent_chat_mcp/static/
# Expected: index.html present (~size of built SPA)

# 4. Wheel builds and includes frontend
cd app/be && uv build
python3 -c "
import zipfile, glob
wheel = sorted(glob.glob('dist/*.whl'))[-1]
with zipfile.ZipFile(wheel) as z:
    names = z.namelist()
    static = [n for n in names if 'static' in n]
    print('Static files in wheel:', static)
    assert any('index.html' in n for n in static), 'index.html missing from wheel!'
    print('OK: frontend bundled')
"
# Expected: OK: frontend bundled

# 5. YAML valid
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/cd.yml'))" && echo "cd.yml: valid"
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))" && echo "ci.yml: valid"
# Expected: both valid

# 6. Deployment skill exists
ls -la ~/.claude-chan/skills/deployment/SKILL.md
# Expected: file present
```

Expected: All checks pass.

## AI Review Findings

| Severity | Source | Finding | Action |
|----------|--------|---------|--------|
| Warning | Architect + Codex + Gemini | `importlib.reload()` re-executes entire app module setup | Fixed: extracted `_default_static_dir()`, test calls function directly |
| Warning | Codex + Architect + Gemini | Non-idempotent `git tag` fails on CD rerun | Fixed: tag/release existence checks added |
| Warning | Architect + Gemini | Duplicate test runs (CI + CD both run tests on same push) | Fixed: removed test jobs from cd.yml; branch protection enforces CI |
| Warning | All reviewers | Long-lived `PYPI_TOKEN` stored as secret | Fixed: OIDC Trusted Publishing, no secret needed |
| Warning | Architect + Gemini | `package.json` version sync is dead code (`private: true`) | Fixed: removed sync step entirely |
| Suggestion | Gemini + Architect | Duplicate tag/release steps | Fixed: single consolidated step with `--prerelease` flag |
| Suggestion | Codex + Architect | Add wheel-content assertion to cd.yml | Fixed: verify step after `uv build` |
| Suggestion | Architect | `workflow_dispatch` for manual trigger | Fixed: added to cd.yml triggers |
| Rejected | Gemini | `cp index.html` misses assets | REJECTED: vite-plugin-singlefile inlines everything |
| Rejected | Gemini | uv cache config wrong | REJECTED: setup-uv@v5 supports these natively |
| Rejected | Codex | Frontend version inconsistency in package.json sync | MOOT: sync step removed |
