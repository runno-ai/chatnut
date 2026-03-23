## Dev Cycle Summary

Cycle: docs/cycles/2026-03-23-mcp-26-mention-notify/

### Pipeline
| Phase | Skill | Status |
|-------|-------|--------|
| 0. Triage | (built-in) | Done |
| 1. Plan | /plan-write | Done (auto-approve) |
| 2. Execute | /plan-execute | Done |
| 3. Code Review | /code-review | Done |
| 4. Push | /push | Done |
| 5. Ship Loop | /ship x 1 | Done |

- Started at: Phase 0 (explicit `--start triage`)
- PR: https://github.com/runno-ai/chatnut/pull/10
- Ship iterations: 1 of 5 max

### Iteration History
| # | Issues In | Fixed | Rejected | Stuck | New After Sync |
|---|-----------|-------|----------|-------|----------------|
| 1 | 0         | 8     | 7        | 0     | 0              |

### Final Status
- CI: All passing (Backend Tests, Frontend, CodeRabbit)
- CodeRabbit: All addressed (8 fixed, 7 rejected)
- Open issues: 0 actionable
- Stuck issues: 0
- Deferred issues: 0
- Result: **CLEAN**

### What Was Built
**MCP-26: Auto-notify agents via SendMessage when @mentioned in chatroom**

New `agent_registry` table + `register_agent` / `list_agents` MCP tools. `post_message` now detects `@<name>` patterns via `(?<!\w)@([\w-]+)` regex, resolves against the room's agent registry (case-insensitive via lowercase normalization), and returns `mentions: [{name, task_id}]` in the response. Callers can then `SendMessage` the mentioned agents.

Key design decisions:
- Return-mentions-to-caller (chatnut provides data, caller acts)
- Case-insensitive matching via `strip().lower()` at both DB and service layers
- Agent name validation: must match `[\w-]+` pattern
- Thread-safe: `register_agent` wrapped in `svc.lock`
- Mention detection before message insert (atomic correctness)

### Files Modified
- `app/be/chatnut/migrations/004_agent_registry.sql` (created)
- `app/be/chatnut/db.py` (modified — CRUD + delete_room cleanup)
- `app/be/chatnut/service.py` (modified — register_agent, list_agents, _detect_mentions)
- `app/be/chatnut/mcp.py` (modified — register_agent, list_agents tools)
- `app/be/tests/test_db.py` (modified — 6 new tests)
- `app/be/tests/test_service.py` (modified — 25 new tests)
- `app/be/tests/test_mcp.py` (modified — 3 new tests + tool registry update)
- `app/be/tests/test_mcp_e2e.py` (modified — 2 new E2E tests)
- `CLAUDE.md` (modified — tools, schema, design decisions)
- `SKILL.md` (modified — agent registration docs)
