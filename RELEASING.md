# Releasing agents-chat-mcp

## Branching Model

```text
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

1. Go to https://pypi.org/manage/project/agents-chat-mcp/settings/publishing/
2. Add a new Trusted Publisher with:
   - **Owner:** `runno-ai`
   - **Repository:** `agents-chat-mcp`
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
4. Verify: `pip install agents-chat-mcp --pre`

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
pip install agents-chat-mcp==0.3.0

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

```text
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
