# CI Security Gates Fix — Implementation Plan

## Context

The CI pipeline has two security gaps found during architecture review (MCP-20, Urgent):
1. `pip-audit || true` swallows all vulnerability findings — CI never fails on known CVEs
2. `app/be/chatnut/static/` is not gitignored — CD builds frontend there, risk of accidental stale commit

## Goal

Make CI security audit actually fail on vulnerabilities and prevent accidental static file commits.

## Architecture

Config-only changes to `.github/workflows/ci.yml` and `.gitignore`. No code, no tests, no behavioral changes.

## Affected Areas

- CI: `.github/workflows/ci.yml`
- Git: `.gitignore`

## Key Files

- `.github/workflows/ci.yml` — lines 46-47, pip-audit step
- `.gitignore` — add static dir exclusion
- `.github/workflows/cd.yml` — reference: lines 70-71 show where static/ is created

## Reusable Utilities

None — config-only changes.

---

## Tasks

### Task 1: Fix pip-audit CI step

**Files:**
- Modify: `.github/workflows/ci.yml:46-47`

**Step 1: Remove `|| true` from pip-audit invocation**

Change line 47 from:
```yaml
          uvx pip-audit --requirement /tmp/audit-reqs.txt || true
```
to:
```yaml
          uvx pip-audit --requirement /tmp/audit-reqs.txt
```

Also clean up line 46 — remove `2>/dev/null` so compile errors are visible in CI logs (keep `|| true` since compile failure is a prep step, not the audit itself):
```yaml
          uv pip compile pyproject.toml --extra test -o /tmp/audit-reqs.txt || true
```

**Step 2: Verify YAML is valid**
```bash
cd /Users/tushuyang/chatnut/.worktrees/mcp-20-ci-security && python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"
```

**Step 3: Commit**
```bash
git add .github/workflows/ci.yml
git commit -m "fix(ci): make pip-audit actually fail on vulnerabilities

Remove || true from pip-audit invocation so CI fails when known CVEs
are found in dependencies. Previously, the audit step was a no-op.

Fixes MCP-20 (1/2)"
```

---

### Task 2: Add static dir to .gitignore

**Files:**
- Modify: `.gitignore`

**Step 1: Add `app/be/chatnut/static/` to .gitignore**

Append after the `build/` line:
```
app/be/chatnut/static/
```

**Step 2: Verify entry is present**
```bash
grep -q 'app/be/chatnut/static/' .gitignore && echo "OK"
```

**Step 3: Commit**
```bash
git add .gitignore
git commit -m "fix(ci): gitignore CD build artifact directory

Add app/be/chatnut/static/ to .gitignore. CD pipeline creates
index.html there during wheel build — without this exclusion,
a local build could accidentally commit a stale frontend.

Fixes MCP-20 (2/2)"
```

---

### Phase 3: Documentation Update

- [ ] No design docs affected (config-only change)
- [ ] No new functions (no docstrings needed)
- [ ] No API changes

---

## Verification

```bash
cd /Users/tushuyang/chatnut/.worktrees/mcp-20-ci-security

# Verify YAML syntax
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"

# Verify pip-audit no longer has || true
! grep -q 'pip-audit.*|| true' .github/workflows/ci.yml && echo "OK: no || true on pip-audit"

# Verify .gitignore has the entry
grep -q 'app/be/chatnut/static/' .gitignore && echo "OK: static dir gitignored"

# Run backend tests (no changes to code, but verify nothing broke)
cd app/be && uv run pytest -x --tb=short
```

Expected: All checks pass, no `|| true` on pip-audit, static dir in .gitignore.
