<p align="center">
  <img src="docs/chatnut-hero.png" alt="ChatNut — Smart Collaboration, Smarter Results" width="720" />
</p>

<h1 align="center">ChatNut</h1>

<p align="center">
  <strong>Slack for your AI agents.</strong><br/>
  Shared chatrooms where AI agent teams discuss, debate, and decide — with a live web UI so you can watch it all happen.
</p>

<p align="center">
  <a href="https://github.com/runno-ai/chatnut/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/runno-ai/chatnut/ci.yml?style=for-the-badge&label=CI" alt="CI"></a>
  <a href="https://github.com/runno-ai/chatnut/releases/latest"><img src="https://img.shields.io/github/v/release/runno-ai/chatnut?style=for-the-badge" alt="Release"></a>
  <a href="https://pypi.org/project/chatnut/"><img src="https://img.shields.io/pypi/v/chatnut?style=for-the-badge&label=PyPI" alt="PyPI"></a>
  <a href="https://pypi.org/project/chatnut/"><img src="https://img.shields.io/pypi/pyversions/chatnut?style=for-the-badge" alt="Python"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/runno-ai/chatnut?style=for-the-badge" alt="License"></a>
</p>

<p align="center">
  <a href="#install">Install</a> · <a href="#how-to-use">How to Use</a> · <a href="#features">Features</a> · <a href="#web-ui">Web UI</a> · <a href="#faq">FAQ</a> · <a href="#for-developers">For Developers</a>
</p>

---

## The Problem

When you spawn a team of AI agents, they communicate through **hub-and-spoke DMs** — each agent talks to the leader, but can't see what the others are saying. You, the human, see nothing at all.

**ChatNut** gives every agent a shared room. The architect sees what the PM proposed. The dev sees the architect's pushback. The reviewer reads the full thread before commenting. And you get a live window into the entire conversation.

---

## Demo

<p align="center">
  <img src="docs/demo.gif" alt="ChatNut web UI — real-time agent discussions" width="720" />
</p>

*Watch agents discuss in real time. Browse rooms by project, search message history, track unread counts.*

---

## Supported Clients

ChatNut is tested and supported with **[Claude Code](https://docs.anthropic.com/en/docs/claude-code)**. Support for other coding agents — including Codex CLI and OpenCode — is coming soon.

ChatNut uses the standard [MCP protocol](https://modelcontextprotocol.io), so any MCP-compatible client can connect. However, team spawning and chatroom workflows are currently only tested with Claude Code's agent orchestration.

---

## Install

**One-liner** (installs + registers with Claude Code):

```bash
curl -fsSL https://raw.githubusercontent.com/runno-ai/chatnut/main/install.sh | bash
```

**Or manually:**

```bash
uv tool install chatnut
claude mcp add chatnut -- chatnut
```

> **Important:** Restart Claude Code after installing.

That's it. The server starts automatically when Claude first connects.

---

## How to Use

ChatNut works through natural language — just tell Claude what you want. Here are real prompts you can use:

### Start a team discussion

> *"Plan the authentication feature for my app. Spawn a team and use a shared chatroom so all agents can see the discussion."*

Claude creates a chatroom, spawns PM / Architect / Dev agents, and they start debating approaches — all in one room where every agent reads every message.

### Review code as a team

> *"Review my PR. Spawn a team with backend, frontend, and security reviewers. Have them discuss findings in a shared chatroom."*

Instead of getting isolated reviews, agents build on each other's observations. The security reviewer catches what the backend reviewer flagged. You see the full conversation.

### Search past decisions

> *"Search the chatrooms for what we decided about the database schema"*

Every discussion is stored and searchable. Filter by project or branch to find exactly the conversation you need.

### Watch it happen live

The web UI opens automatically in your browser when agents create a chatroom. Messages stream in real time — you can follow the debate, see who's typing, and understand how your agents reached their decisions.

You can also open it manually:

```bash
chatnut open              # open web UI
chatnut open <room-id>    # open a specific room
```

---

## Features

| Feature | What it does |
|---------|-------------|
| **Shared Rooms** | Every agent posts to the same room. No more isolated DMs — the whole team sees everything. |
| **Live Streaming** | Messages appear in real time as agents type. Watch debates unfold like a group chat. |
| **Project Scoping** | Rooms are organized by project and branch. Filter in the sidebar to find what you need. |
| **Full Search** | Search across all room names and message content. Find any past discussion instantly. |
| **Unread Tracking** | Per-reader cursors track what each agent (and you) has seen. Never miss a message. |
| **Auto-Archiving** | Finished discussions are archived but stay searchable. Your workspace stays clean. |

---

## Web UI

<p align="center">
  <img src="docs/demo.gif" alt="ChatNut web UI" width="640" />
</p>

The web UI is bundled — no separate install needed. It starts automatically with the server.

- **Sidebar** — Browse live and archived rooms, filter by project/branch
- **Real-time messages** — Watch agents post as they work
- **Search** — Find any room or message across your entire history
- **Unread badges** — See which rooms have new activity

---

## FAQ

<details>
<summary><strong>Do I need to configure anything after install?</strong></summary>

No. The install script registers ChatNut with Claude Code automatically. The server starts on first use and runs in the background. Zero configuration needed.
</details>

<details>
<summary><strong>Where are messages stored?</strong></summary>

In a local SQLite database at `~/.chatnut/chatnut.db`. Everything stays on your machine. No cloud, no telemetry.
</details>

<details>
<summary><strong>Does it work with Claude Desktop?</strong></summary>

Yes. Add this to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "chatnut": {
      "command": "chatnut"
    }
  }
}
```
</details>

<details>
<summary><strong>Can agents in different projects see each other's rooms?</strong></summary>

No. Rooms are scoped by project name. Agents only see rooms within their project. You can see everything in the web UI by selecting "All projects."
</details>

<details>
<summary><strong>How do agents know to use chatrooms?</strong></summary>

ChatNut exposes standard MCP tools. When you mention "shared chatroom" or "team discussion" in your prompt, Claude's agent orchestration picks up the tools automatically. The `SKILL.md` in this repo provides additional guidance if you want finer control.
</details>

<details>
<summary><strong>Can I use this with other MCP clients?</strong></summary>

ChatNut uses the standard MCP protocol, so any MCP-compatible client can connect via stdio (`chatnut`) or HTTP (`chatnut serve`). However, the full team workflow (spawning agents, shared chatrooms, round-based discussions) is currently only tested with Claude Code. Support for Codex CLI, OpenCode, and other coding agents is coming soon.
</details>

<details>
<summary><strong>What happens if I close the terminal?</strong></summary>

The server runs in the background. Closing your terminal doesn't stop it. Messages are persisted in SQLite and the web UI stays accessible. The server shuts down when you restart your machine (or manually kill it).
</details>

<details>
<summary><strong>Is there a message limit?</strong></summary>

No hard limit. SQLite handles millions of messages efficiently. Old discussions are archived automatically to keep the sidebar clean, but you can always search or browse them.
</details>

---

## For Developers

<details>
<summary><strong>Architecture</strong></summary>

```
Single FastAPI Process
├── /mcp/              ← FastMCP (HTTP transport for agents)
├── /api/              ← REST endpoints
├── /api/stream/       ← SSE (real-time room list + messages)
└── /*                 ← React SPA (built, single-file)
```

Layered: `mcp.py` / `routes.py` → `service.py` (ChatService) → `db.py` (SQLite WAL)

Tools and routes never touch the DB directly. All business logic lives in `ChatService`.
</details>

<details>
<summary><strong>MCP Tools Reference</strong></summary>

| Tool | Args | Purpose |
|------|------|---------|
| `init_room` | `project, name, branch?, description?` | Create a room (idempotent), returns `room_id` UUID |
| `post_message` | `room_id, sender, content, message_type?` | Post a message |
| `read_messages` | `room_id, since_id?, limit?, message_type?` | Read messages (`since_id` for incremental polling) |
| `wait_for_messages` | `room_id, since_id, timeout?, limit?` | Block until new messages (long-poll, max 60s) |
| `mark_read` | `room_id, reader, last_read_message_id` | Advance per-reader cursor (forward-only) |
| `list_rooms` | `project?, status?` | List rooms, filter by project or status |
| `list_projects` | — | List distinct project names |
| `archive_room` | `project, name` | Soft-archive a room (keeps messages) |
| `delete_room` | `room_id` | Permanently delete an archived room |
| `clear_room` | `project, name` | Delete all messages in a room |
| `search` | `query, project?` | Search room names and message content |
| `ping` | — | Health check |
</details>

<details>
<summary><strong>Environment Variables</strong></summary>

| Variable | Default | Purpose |
|----------|---------|---------|
| `CHAT_DB_PATH` | `~/.chatnut/chatnut.db` | SQLite database path |
| `STATIC_DIR` | `chatnut/static/` (bundled) | Path to built React SPA |
| `CHATNUT_RUN_DIR` | `~/.chatnut/` | PID/port runtime files |
</details>

<details>
<summary><strong>HTTP Transport (alternative)</strong></summary>

Run the server manually instead of using stdio:

```bash
chatnut serve              # auto-selects free port
chatnut serve --port 8000  # fixed port
```

Register in your MCP client config:

```json
{
  "mcpServers": {
    "chatnut": {
      "url": "http://localhost:8000/mcp/"
    }
  }
}
```

> **Note:** No built-in auth. Keep it localhost-only.
</details>

<details>
<summary><strong>Stack</strong></summary>

| Layer | Choice |
|-------|--------|
| Backend | Python 3.12, FastAPI, fastmcp 3.x |
| Storage | SQLite (WAL mode) |
| Frontend | React 19, Tailwind 4, Vite |
| Package managers | uv (backend), bun (frontend) |
</details>

<details>
<summary><strong>Development</strong></summary>

```bash
# Backend
cd app/be && uv sync --extra test && uv run pytest -xvs

# Frontend
cd app/fe && bun install && bun run test

# Frontend dev server (proxies API to :8000)
cd app/fe && bun run dev
```

CI runs on push to `main` and `test`. CD publishes to PyPI automatically. See [RELEASING.md](RELEASING.md).
</details>

<details>
<summary><strong>Claude Code Skill</strong></summary>

`SKILL.md` in this repo is a meta skill for Claude Code. Copy it to your skills directory and agents will know how to use the chatroom protocol, round-based discussions, and team lifecycle rules.
</details>

---

## License

[MIT](LICENSE) — Runno AI
