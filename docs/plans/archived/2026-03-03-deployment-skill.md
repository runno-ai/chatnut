# Deployment Skill + CD Simplification

## Context

The project currently has automatic CD triggered by CI completion on `test`/`main` branches, with a pre-release model via the `test` branch. This adds complexity without value for a greenfield project. We need a `/deployment` skill that gives the developer full control over releases — reviewing changes, recommending version bumps, drafting release notes, and manually triggering CD.

## Goal

Create a `/deployment` skill that is the sole release mechanism, and simplify the CD pipeline to `workflow_dispatch` only (no automatic triggers, no `test` branch, no pre-releases).

## Architecture

The skill runs locally, analyzes git history since last release tag, categorizes commits by conventional commit prefixes, recommends a semver bump, presents a release notes draft, and on approval bumps version + commits + pushes + waits for CI + triggers CD. The CD workflow becomes a pure build-and-publish pipeline triggered only by `workflow_dispatch`.

**Key invariant:** The skill is the sole CI gate. It verifies CI passes on the pushed commit before triggering CD. The CD workflow itself has no CI prerequisite — it trusts the caller.

## Affected Areas

- Skill: `~/.claude/skills/deployment/SKILL.md` (new)
- CI/CD: `.github/workflows/cd.yml`, `.github/workflows/ci.yml`
- Docs: `RELEASING.md`, `CLAUDE.md`

## Key Files

- `.github/workflows/cd.yml` — CD pipeline, remove `workflow_run` trigger and `test` branch logic
- `.github/workflows/ci.yml` — CI pipeline, remove `test` branch from triggers
- `RELEASING.md` — Release documentation, simplify to `/deployment` workflow
- `CLAUDE.md` — Project docs, update CD section
- `~/.claude/skills/deployment/SKILL.md` — New skill file

## Reusable Utilities

- `gh release list --repo runno-ai/chatnut` — detect last release tag
- `git log <tag>..HEAD --format='%s'` — gather commits since last release
- `gh workflow run cd.yml --ref main` — trigger CD manually
- `gh run list --workflow=ci.yml` — verify CI status before CD trigger

---

## Tasks

### Task 1: Create `/deployment` skill

**Files:**
- Create: `~/.claude/skills/deployment/SKILL.md`

**Skill content:**

```markdown
---
name: deployment
title: Deploy & Release
description: Review changes since last release, recommend version bump and release notes, then trigger CD pipeline
aliases: [deploy, release]
---

# Deployment

Release controller for ChatNut. Reviews all changes since the last release, recommends a version bump, drafts release notes, and triggers the CD pipeline.

## Guards

1. **Must be on `main` branch** — `git branch --show-current` must be `main`. Abort if not.
2. **Working tree must be clean** — `git status --porcelain` must be empty. Abort if not.
3. **Must be in the chatnut repo** — check for `app/be/pyproject.toml`. Abort if not.
4. **Local main must match origin** — `git fetch origin main && git diff --quiet HEAD origin/main`. Abort if diverged.

## Workflow

### Step 1: Detect Last Release

```bash
LAST_TAG=$(gh release list --repo runno-ai/chatnut --limit 1 --json tagName -q '.[0].tagName')
if [ -z "$LAST_TAG" ]; then
  LAST_TAG=$(git rev-list --max-parents=0 HEAD)
fi
echo "Last release: $LAST_TAG"
```

### Step 2: Check for Retry State

Before gathering changes, check if we're in a "version bumped but release failed" state:

```bash
CURRENT_VERSION=$(python3 -c "import tomllib; print(tomllib.load(open('app/be/pyproject.toml','rb'))['project']['version'])")
LAST_RELEASE_VERSION=${LAST_TAG#v}  # strip 'v' prefix

if [ "$CURRENT_VERSION" != "$LAST_RELEASE_VERSION" ]; then
  # Version in pyproject.toml doesn't match last release — check if tag exists
  if ! gh release view "v$CURRENT_VERSION" &>/dev/null; then
    echo "Detected: version $CURRENT_VERSION is bumped but not released."
    echo "Offering retry for v$CURRENT_VERSION..."
    # Skip to Step 4 with retry option
  fi
fi
```

If retry state detected, present user with:
- **Retry release for vX.Y.Z** — skip version bump, go straight to push + CI + CD
- **Start fresh** — analyze commits and recommend a new bump (overwriting the current version)
- **Abort**

### Step 3: Gather & Analyze Changes

```bash
git log "$LAST_TAG"..HEAD --format='%h %s' --no-merges
git diff "$LAST_TAG"..HEAD --stat
```

If **no commits since last release**, report "Nothing to release since $LAST_TAG" and stop.

Parse each commit subject by conventional commit prefix:

| Prefix | Category | Bump |
|--------|----------|------|
| `feat:` | Features | minor |
| `fix:` | Bug Fixes | patch |
| `refactor:` | Refactoring | patch |
| `docs:` | Documentation | — |
| `ci:` | CI/CD | — |
| `chore:` | Maintenance | — |
| `BREAKING CHANGE` or `!:` | Breaking | major |
| (no prefix) | Other | patch |

**Version bump recommendation** (highest wins):
- Any `BREAKING CHANGE` or `!:` → **major**
- Any `feat:` → **minor**
- Only `fix:`/`refactor:`/`chore:`/`docs:`/`ci:` → **patch**
- Only `docs:`/`ci:` → suggest skipping release (no functional changes)

**Compute next version:** Read current version from `app/be/pyproject.toml`, apply the recommended bump. Example: `0.3.0` + minor → `0.4.0`.

### Step 4: Present to User

Show:
1. **Changes since last release** — grouped by category
2. **Recommended version bump** — e.g., `0.3.0 → 0.4.0 (minor: new features)`
3. **Draft release notes** — categorized commit list

Use `AskUserQuestion` to let the user:
- Accept the recommended version
- Override with a different version
- Abort the release

### Step 5: Execute Release

After user confirms:

1. **Bump version** in `app/be/pyproject.toml` — set to the confirmed version
2. **Commit**: `chore: bump version to X.Y.Z`
3. **Push** to `main`
4. **Wait for CI** — poll `gh run list --workflow=ci.yml --branch main --commit $(git rev-parse HEAD)` until conclusion is `success` or `failure`. If CI fails, report and stop (version bump is on main but release is aborted — next `/deployment` run will detect the retry state in Step 2).
5. **Trigger CD**: `gh workflow run cd.yml --repo runno-ai/chatnut --ref main`
6. **Wait for CD** — `gh run watch` blocks until the CD run completes:
   ```bash
   # Get the run ID (latest CD run on main)
   sleep 5  # brief wait for run to appear
   RUN_ID=$(gh run list --workflow=cd.yml --branch main --limit 1 --json databaseId -q '.[0].databaseId')
   gh run watch "$RUN_ID" --exit-status
   ```
   If CD fails, report the failure and stop. The version bump commit is on main — next `/deployment` run will detect the retry state in Step 2.
7. **Verify** (only after CD completes successfully):
   - `gh release view vX.Y.Z --repo runno-ai/chatnut` — confirm GitHub Release exists
   - `python3 -c "import urllib.request; urllib.request.urlopen('https://pypi.org/pypi/chatnut/X.Y.Z/json'); print('Published to PyPI')"` — confirm PyPI availability

## Error Handling

- **Not on main**: "Switch to main branch first. Aborting."
- **Dirty working tree**: "Uncommitted changes detected. Commit or stash first."
- **Local diverged from origin**: "Local main differs from origin/main. Pull first."
- **No changes since last release**: "Nothing to release since vX.Y.Z."
- **CI fails after push**: "CI failed. Version bump is on main but release aborted. Run `/deployment` again to retry."
- **CD fails**: "CD failed. Version bump is on main but release not published. Run `/deployment` again to retry."
- **CD trigger fails**: Report error, don't retry.
- **Push fails**: Report error, don't retry (follows push-once rule).

## Handling Bad Releases

PyPI versions are immutable — you cannot delete or overwrite a published version. If a bad version is released:

1. Fix the bug on main
2. Run `/deployment` — it will recommend a patch bump (e.g., `1.2.3` → `1.2.4`)
3. The patch release supersedes the bad version
```

---

### Task 2: Simplify CD workflow

**Files:**
- Modify: `.github/workflows/cd.yml`

**Changes:**

1. Remove `workflow_run` trigger — keep only `workflow_dispatch`
2. Remove all `test` branch logic — no pre-release version computation
3. Simplify version step — read directly from `pyproject.toml`
4. Remove pre-release conditionals — no `is_prerelease`, no `rc` suffix
5. Replace silent `if: github.ref_name == 'main'` with explicit validation step that fails loudly
6. Remove `workflow_run`-specific checkout ref logic

**Target `cd.yml`:**

```yaml
name: CD

on:
  workflow_dispatch:

concurrency:
  group: cd-${{ github.ref }}
  cancel-in-progress: false

jobs:
  publish:
    name: Build & Publish
    runs-on: ubuntu-latest
    timeout-minutes: 20
    permissions:
      contents: write
      id-token: write
    steps:
      - name: Validate branch
        run: |
          if [[ "${{ github.ref_name }}" != "main" ]]; then
            echo "ERROR: CD can only run on main branch, got: ${{ github.ref_name }}"
            exit 1
          fi

      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
          fetch-tags: true

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

      - name: Read version from pyproject.toml
        id: version
        run: |
          VERSION=$(python3 -c "
          import tomllib
          with open('app/be/pyproject.toml', 'rb') as f:
              data = tomllib.load(f)
          print(data['project']['version'])
          ")
          echo "version=$VERSION" >> "$GITHUB_OUTPUT"
          echo "Publishing version: $VERSION"

      - name: Install frontend deps
        working-directory: app/fe
        run: bun install --frozen-lockfile

      - name: Build frontend
        working-directory: app/fe
        run: bun run build

      - name: Bundle frontend into package
        run: |
          mkdir -p app/be/chatnut/static
          cp app/fe/dist/index.html app/be/chatnut/static/index.html
          echo "Bundled frontend:"
          ls -lh app/be/chatnut/static/

      - name: Build wheel
        working-directory: app/be
        run: |
          rm -rf dist/
          uv build

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

      - name: Publish to PyPI
        working-directory: app/be
        run: |
          VERSION="${{ steps.version.outputs.version }}"
          EXISTS=$(python3 -c "
          import urllib.request, sys
          try:
              urllib.request.urlopen('https://pypi.org/pypi/chatnut/${VERSION}/json')
              print('true')
          except Exception:
              print('false')
          ")
          if [[ "$EXISTS" == "true" ]]; then
            echo "Version $VERSION already on PyPI — skipping publish"
          else
            uv publish --trusted-publishing always
          fi

      - name: Create tag and GitHub Release
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          VERSION="${{ steps.version.outputs.version }}"
          TAG="v${VERSION}"

          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"

          if git ls-remote --exit-code --tags origin "refs/tags/$TAG" >/dev/null 2>&1; then
            echo "Tag $TAG already exists — skipping tag creation"
          else
            git tag -a "$TAG" -m "Release $TAG"
            git push origin "$TAG"
          fi

          if gh release view "$TAG" &>/dev/null; then
            echo "Release $TAG already exists — skipping"
          else
            gh release create "$TAG" \
              --title "Release $TAG" \
              --generate-notes \
              --verify-tag
          fi
```

---

### Task 3: Simplify CI workflow

**Files:**
- Modify: `.github/workflows/ci.yml`

**Changes:**

Remove `test` from branch triggers:

```yaml
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
```

---

### Task 4: Update RELEASING.md

**Files:**
- Modify: `RELEASING.md`

**Rewrite** to reflect the new model:

```markdown
# Releasing ChatNut

## How to Release

Use the `/deployment` skill — it handles everything:

```text
/deployment
```

The skill will:
1. Detect the last release and gather all changes since
2. Categorize commits and recommend a semver bump
3. Draft release notes for your review
4. On approval: bump version, commit, push, wait for CI, trigger CD
5. Verify the release on PyPI and GitHub

## What Happens Under the Hood

```text
/deployment
  ├── Detect last release tag (gh release list)
  ├── Gather commits since tag (git log)
  ├── Parse conventional commits → recommend bump
  ├── Present release notes + version to user
  ├── Bump version in pyproject.toml
  ├── Commit + push to main
  ├── Wait for CI to pass
  ├── Trigger CD (gh workflow run cd.yml)
  └── Verify: PyPI + GitHub Release
```

CD pipeline (`cd.yml`) builds the wheel with bundled frontend and publishes to PyPI via OIDC Trusted Publishing.

## One-Time Setup: PyPI Trusted Publisher

Configure once in PyPI project settings:

1. Go to https://pypi.org/manage/project/chatnut/settings/publishing/
2. Add a new Trusted Publisher with:
   - **Owner:** `runno-ai`
   - **Repository:** `chatnut`
   - **Workflow filename:** `cd.yml`
   - **Environment:** _(leave blank)_
3. Save. No GitHub secret needed.

## Manual Release (without skill)

If you need to release without the skill:

1. Bump version in `app/be/pyproject.toml`
2. Commit: `git commit -m "chore: bump version to X.Y.Z"`
3. Push to main, wait for CI to pass
4. Trigger CD: `gh workflow run cd.yml --repo runno-ai/chatnut --ref main`

## Monitoring

```bash
# Recent CD runs
gh run list --workflow=cd.yml --repo runno-ai/chatnut --limit 5

# Latest run details
gh run view --repo runno-ai/chatnut

# Check PyPI
pip install chatnut==X.Y.Z
```

## Conventional Commits

Use these prefixes for clean auto-generated release notes:

| Prefix | Meaning | Bump |
|--------|---------|------|
| `feat:` | New feature | minor |
| `fix:` | Bug fix | patch |
| `refactor:` | Refactoring | patch |
| `chore:` | Maintenance | — |
| `docs:` | Documentation | — |
| `ci:` | CI/CD changes | — |
```

---

### Task 5: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

**Update the CD section** to:

```markdown
## CD

`.github/workflows/cd.yml` is triggered **only via `workflow_dispatch`** — either by the `/deployment` skill or manually via `gh workflow run cd.yml --ref main`.

- Builds frontend, bundles into Python wheel
- Publishes to PyPI via OIDC Trusted Publishing
- Creates git tag + GitHub Release with auto-generated notes

Uses PyPI OIDC Trusted Publishing (no stored secrets). See [RELEASING.md](RELEASING.md).
```

Also remove any `test` branch references in the CI section (change "runs on push to `main` and `test`" to "runs on push to `main`").

---

### Task 6: Cleanup

- [ ] Verify no other files reference `test` branch in release context (grep for `branches:.*test` in workflows)
- [ ] Note: `test` branch deletion and GitHub branch protection removal are manual steps (not automated in this plan)

---

## Verification

After all tasks:

```bash
# Verify CD has no workflow_run trigger
grep -c 'workflow_run' .github/workflows/cd.yml  # expect: 0

# Verify CD has workflow_dispatch
grep -c 'workflow_dispatch' .github/workflows/cd.yml  # expect: 1

# Verify CD fails loudly on non-main
grep 'ERROR.*CD can only run on main' .github/workflows/cd.yml  # expect: match

# Verify CI has no test branch in triggers
grep 'branches:' .github/workflows/ci.yml  # expect: only [main]

# Verify skill file exists with correct frontmatter
head -5 ~/.claude/skills/deployment/SKILL.md  # expect: name: deployment

# Run backend tests
cd app/be && uv run pytest -xvs
```

Expected: All checks pass, no test failures.

## AI Review Findings

| Severity | Source | Finding | Action |
|----------|--------|---------|--------|
| Critical | Architect + DevOps + Codex | No CI gate before CD trigger | Added: Skill Step 5 waits for CI to pass before triggering CD |
| Critical | Architect | Version computation unclear | Added: Step 3 explicitly computes next_version from current + bump |
| High | Gemini | `gh workflow run` is async — skill needs synchronous monitoring | Added: Step 6 uses `gh run watch` to block until CD completes |
| High | Gemini | PyPI verification fails due to propagation delay | Fixed: Verification only runs after `gh run watch` confirms CD success |
| Warning | Architect | Orphaned version bump if CD fails | Added: Step 2 retry state detection |
| Warning | Architect + DevOps + Gemini | `pip install --dry-run` nonexistent | Fixed: Use PyPI JSON API + `gh release view` |
| Warning | Architect + DevOps + Codex | Silent skip on non-main dispatch | Fixed: Explicit validation step that fails with error message |
| Warning | DevOps | Test branch cleanup not addressed | Added: Task 6 notes manual cleanup needed |
| Warning | Codex | Stale wheel artifacts in dist/ | Fixed: Added `rm -rf dist/` before `uv build` in CD |
| Warning | Gemini | No rollback procedure documented | Added: "Handling Bad Releases" section in skill |
| Suggestion | DevOps | Verify local main matches origin | Added: Guard #4 in skill |
| Suggestion | Architect + DevOps + Gemini | Verification grep too broad | Fixed: Specific patterns in Verification section |
| Suggestion | Gemini | Race condition push vs dispatch | Noted: Low risk — `gh run watch` catches any issue |
| Suggestion | Codex | Add workflow_dispatch inputs for auditability | Deferred: Keep workflow simple for v1 |
