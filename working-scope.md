---
scope: go-public-prep
issues:
  - id: MCP-1
    title: Legal & project metadata
    status: In Progress
  - id: MCP-2
    title: Code correctness blockers
    status: In Progress
  - id: MCP-3
    title: Scrub internal references from codebase
    status: In Progress
execution_order:
  - [MCP-1, MCP-2, MCP-3]   # all independent — fully parallel
out_of_scope:
  - MCP-4   # README & docs completeness — blocked by MCP-1, create after this merges
  - MCP-5   # Code & config fixes — blocked by MCP-2, create after this merges
  - MCP-8   # Open-source polish — blocked by MCP-1, MCP-3, MCP-4
  - MCP-9   # Demo GIF — blocked by MCP-3, MCP-4
affected_paths:
  - LICENSE
  - app/be/pyproject.toml
  - app/fe/package.json
  - app/be/agent_chat_mcp/app.py
  - app/be/agent_chat_mcp/mcp.py
  - docs/skill-migration.md
  - app/be/scripts/import_archive.py
  - .coderabbit.yaml
  - SKILL.md
  - CLAUDE.md
---

# Working Scope: go-public-prep

## Issues in Scope

All three are fully independent — no blockers between them. Implement in parallel.

- **MCP-1**: Legal & project metadata (In Progress)
- **MCP-2**: Code correctness blockers (In Progress)
- **MCP-3**: Scrub internal references from codebase (In Progress)

## Execution Order

**Step 1 — All parallel (no interdependencies):**
- MCP-1, MCP-2, MCP-3

## MCP-1: Legal & project metadata

- Add `LICENSE` (MIT) to repo root
- `app/be/pyproject.toml`: add `authors`, `license = {text = "MIT"}`, `[project.urls]` with `repository` and `homepage` pointing to `https://github.com/runno-ai/agent-chat-mcp`

## MCP-2: Code correctness blockers

- `app/be/pyproject.toml`: change `fastmcp>=2.0.0` → `fastmcp>=3.0.0`
- `app/be/agent_chat_mcp/app.py` + `mcp.py`: change default DB path from `~/.claude/agent-chat.db` → `~/.agent-chat/agent-chat.db`
- Update README and CLAUDE.md to reflect new default path

## MCP-3: Scrub internal references

- `docs/skill-migration.md` — delete (entirely internal portless/launchd setup; not useful to public)
- `.coderabbit.yaml` — update `path_instructions` to use `agent_chat_mcp/` (not `team_chat_mcp/`); remove `DESIGN.md` entry
- `app/be/scripts/import_archive.py` — remove hardcoded `runno`/`runno-agent-sdk`/`team-chat-mcp` project detection; replace with generic passthrough or remove the auto-detect function entirely
- `SKILL.md` front matter — update `name: team-chat` → `name: agent-chat`, `aliases: [team-chat]` → `aliases: [agent-chat]`
- `CLAUDE.md` line 137 — remove `~/.claude-chan/skills/team-chat/SKILL.md` reference (personal internal path)

## Out of Scope (Future WT — create after this merges)

- **MCP-4**: README & documentation completeness — blocked by MCP-1
- **MCP-5**: Code & config fixes — blocked by MCP-2
- **MCP-8**: Open-source polish — blocked by MCP-1, MCP-3, MCP-4
- **MCP-9**: Demo GIF — blocked by MCP-3, MCP-4

## Validation

```bash
cd app/be && uv run pytest -xvs
```
