## Dev Cycle Summary

Cycle: docs/cycles/2026-03-23-mcp-21-22-backend-reliability/

### Pipeline
| Phase | Skill | Status |
|-------|-------|--------|
| 0. Triage | (built-in) | Done |
| 1. Plan | /plan-write | Done |
| 2. Execute | /plan-execute | Done |
| 3. Code Review | /code-review | Done |
| 4. Push | /push | Done |
| 5. Ship Loop | /ship x 1 | Done |

- Started at: Phase 0 (explicit --start triage)
- PR: https://github.com/runno-ai/chatnut/pull/9
- Ship iterations: 1 of 5 max

### Iteration History
| # | Issues In | Fixed | Rejected | Stuck | New After Sync |
|---|-----------|-------|----------|-------|----------------|
| 1 | 0         | 6     | 21       | 0     | 0              |

### Final Status
- CI: All passing (Backend Tests, Frontend, CodeRabbit)
- CodeRabbit: All addressed (6 fixed, 21 rejected)
- Open issues: 0 actionable
- Stuck issues: 0
- Deferred issues: 0
- Result: **CLEAN**

### Issues Fixed (6)
| # | Source | File | Summary |
|---|--------|------|---------|
| 1 | outside_diff | CLAUDE.md | Updated Schema to show ON DELETE CASCADE on messages FK |
| 2 | inline | test_cli.py | Added concurrent double-start race test for _ensure_server |
| 3 | inline | test_app_startup.py | Isolated test from real app dependencies |
| 4 | inline | working-scope.md | Fixed lock artifact reference (PID file → server.lock) |
| 5 | inline | working-scope.md | Updated issue statuses from Backlog to In Review |
| 6 | inline | working-scope.md | Renamed affected_crates to affected_files |

### Issues Rejected (21)
Mostly PR summary boilerplate suggestions (platform guards, deployment guides, staging tests, NFS warnings) that don't apply to this local dev tool. Two inline rejections:
- Lock file handle leak on early return — technically incorrect (Python finally runs on return)
- Symbol-only lock test — behavior already exercised by 19 tests in test_wait_for_messages.py

### Changes Delivered
| Issue | Title | Commits |
|-------|-------|---------|
| MCP-21 | Server startup race condition and lock clarity | 3 commits |
| MCP-22 | Database schema integrity gaps | 3 commits |

**MCP-21 fixes:**
1. `_ensure_server()` race condition fixed with `fcntl.flock` on `server.lock`
2. `svc.lock` renamed to `_wait_notify_lock`, moved to `mcp.py` module-level
3. Single-worker requirement documented in CLAUDE.md and startup log

**MCP-22 fixes:**
1. `ON DELETE CASCADE` added to messages FK via migration 004 (with AUTOINCREMENT preservation)
2. `create_room()` logs at DEBUG level when UUID is discarded on idempotent create
3. `_now()` hardened with explicit `strftime` for `+00:00` format, `auto_archive_stale_rooms` cutoff made consistent

### Test Coverage
- 298 tests total (8 new tests added)
- All passing
