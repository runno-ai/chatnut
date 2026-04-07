---
name: deploy
title: Deploy & Release
description: Review changes since last release, recommend version bump and release notes, then trigger CD pipeline
---

# Deploy

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
8. **Update local install** — reinstall the global CLI from PyPI so the local `chatnut` matches the released version:
   ```bash
   uv tool install --force chatnut
   chatnut serve &  # restart server with new version
   sleep 2
   curl -s "http://127.0.0.1:$(cat ~/.chatnut/server.port)/api/status"
   ```
   If the install fails, report but don't block — the release itself succeeded.

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

## SDK Deployment (`/deployment sdk`)

When called with argument `sdk`, runs the SDK release pipeline instead of the
platform deployment:

1. **Verify the SDK subtree is clean:**
   ```bash
   cd /Users/tushuyang/runno/main
   git diff HEAD -- crates/runno-agent-sdk/ | head -20
   ```
   If uncommitted changes exist, stop and ask the user to commit first.

2. **Gather & analyze changes since last SDK release:**
   ```bash
   LAST_SDK_TAG=$(git tag -l 'sdk-v*' --sort=-v:refname | head -1)
   echo "Last SDK release: $LAST_SDK_TAG"
   git log "$LAST_SDK_TAG"..HEAD --format='%h %s' -- crates/runno-agent-sdk/
   git diff "$LAST_SDK_TAG"..HEAD --stat -- crates/runno-agent-sdk/
   ```
   If **no commits since last tag**, report "Nothing to release since $LAST_SDK_TAG" and stop.

   Parse each commit using the same conventional commit rules as the platform workflow
   (feat→minor, fix→patch, breaking→major, docs/ci/chore→skip). Compute the recommended
   bump from the highest-priority category.

3. **Present changes and recommend version:**
   - Read the current version from `crates/runno-agent-sdk/Cargo.toml` → `[package].version`
   - Show the categorized commit list and file diff stats
   - Present the recommended bump with `AskUserQuestion` (accept / override / abort)
   - Apply the confirmed bump to `Cargo.toml` (and any sub-crate `Cargo.toml` files that pin their own version)

4. **Tag and push:**
   ```bash
   TAG="sdk-v$(grep '^version' crates/runno-agent-sdk/Cargo.toml | head -1 | grep -oP '[\d.]+')"
   git tag "$TAG"
   git push origin "$TAG"
   ```

5. **Monitor the release workflow:**
   ```bash
   gh run watch --repo runno-ai/runno $(gh run list --workflow sdk-release.yml --limit 1 --json databaseId --jq '.[0].databaseId')
   ```

6. **Confirm success:** Check that the release appears on `runno-ai/runno-agent-sdk`.

7. **Rebuild and reinstall the `agent-mcp-server` binary (smart — skips if already current):**
   ```bash
   ~/.claude/skills/deployment/build-mcp-binary.sh "$VERSION"
   ```
   The script checks the installed binary's version first and skips the Cargo build if it already
   matches. If the build fails, report the error but don't block — the SDK release itself succeeded.

   **Note:** Claude Code must be restarted to pick up the new binary.
