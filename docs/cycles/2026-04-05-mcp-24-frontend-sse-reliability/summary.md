## Dev Cycle Summary

Cycle: docs/cycles/2026-04-05-mcp-24-frontend-sse-reliability/

### Pipeline
| Phase | Skill | Status |
|-------|-------|--------|
| 0. Triage | (skipped — auto-cycle) | Skipped |
| 1. Plan Draft | /plan-draft | Done |
| 2. Plan Review | /plan-review | Done |
| 3. Execute | /plan-execute | Done |
| 4. Code Review | /code-review | Done |
| 5. Push | /push | Done |
| 6. Ship Loop | /ship x 1 | Done |

- Started at: Phase 1 (plan-draft, via --start plan-draft)
- PR: https://github.com/runno-ai/chatnut/pull/11
- Ship iterations: 1 of 5 max

### Iteration History
| # | Issues In | Fixed | Rejected | Stuck | New After Sync |
|---|-----------|-------|----------|-------|----------------|
| 1 | 0         | 7     | 5        | 0     | 0              |

### Final Status
- CI: All passing (Backend Tests, Frontend, CodeRabbit)
- CodeRabbit: All addressed
- Open issues: 0 actionable
- Stuck issues: 0
- Deferred to Linear: 0
- Result: **CLEAN**

### Changes Made
- `app/fe/src/hooks/useSSE.ts` — Replaced manual EventSource close/recreate with native browser auto-reconnect. Added permanent error detection (readyState === CLOSED). Browser natively sends Last-Event-Id header on reconnect.
- `app/fe/src/hooks/__tests__/useSSE.test.ts` — Updated 2 existing tests, added 4 new tests for native reconnect behavior (14 total, all passing).
- `app/fe/src/hooks/__tests__/helpers.ts` — MockEventSource._triggerError now accepts optional readyState param.
- `app/fe/vite.config.ts` — Dev proxy port reads CHATNUT_DEV_PORT env var (fallback 8000).
- `app/be/pyproject.toml` — Upgraded fastmcp 3.0.2 → 3.2.0 (CVE-2025-64340, CVE-2026-27124).
- `CLAUDE.md` — Added CHATNUT_DEV_PORT to environment variables table.
- `docs/cycles/2026-04-05-mcp-24-frontend-sse-reliability/plan.md` — Implementation plan.

### Key Architecture Decision
Original plan used manual Last-Event-Id tracking via useRef + since_id query param. Domain team (Architect + Frontend Dev) identified that the backend only accepts Last-Event-Id as an HTTP header, not a query param. Restructured to use native browser EventSource auto-reconnect, which sends the header automatically. Zero backend changes needed.
