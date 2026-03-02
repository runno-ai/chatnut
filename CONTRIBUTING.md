# Contributing to agents-chat-mcp

Thank you for contributing! This guide covers local setup, running tests, and the PR process.

## Prerequisites

- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- [bun](https://bun.sh/) (for frontend work)

## Local Setup

**Backend:**
```bash
cd app/be
uv sync --extra test
```

**Frontend:**
```bash
cd app/fe
bun install
```

## Running Tests

**Backend:**
```bash
cd app/be && uv run pytest -xvs
```

**Frontend:**
```bash
cd app/fe && bun run test
```

## Running the Server

```bash
# Production DB
cd app/be && uv run uvicorn agents_chat_mcp.app:app --port 8000

# Dev DB (rich seed data, reseeds on start)
# Requires: CHAT_DB_PATH=../../data/dev.db
cd app/be && CHAT_DB_PATH=../../data/dev.db uv run uvicorn agents_chat_mcp.app:app --port 8000
```

Open `http://localhost:8000` to view the UI.

## Code Style

- **Python:** no enforced formatter, but keep functions short and well-named
- **TypeScript:** `tsc --noEmit` must pass; no unused imports

## Pull Request Process

1. Fork the repo and create a feature branch
2. Run backend and frontend tests — both must pass
3. Update `README.md` or `SKILL.md` if your change affects the public API or usage
4. Open a PR targeting `main` with a clear description of what changed and why

## Seed Data

The dev fixture DB lives at `data/dev.db` (committed). If you add new features that
should be reflected in demo data, update `data/seed.py` and run:

```bash
cd app/be && uv run python ../../data/seed.py --reset
git add data/dev.db data/seed.py
git commit -m "data: update seed data"
```
