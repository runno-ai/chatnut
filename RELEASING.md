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
