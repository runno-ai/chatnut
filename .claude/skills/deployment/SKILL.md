# Deployment Skill

Use when monitoring or triggering the chatnut CD pipeline. Checks workflow
status, shows recent runs, and can trigger manual workflow dispatch.

## Usage

```
/deployment            → show recent CD runs
/deployment status     → show latest run status
/deployment logs       → show logs for latest CD run
/deployment trigger    → manually dispatch CD workflow on current branch
```

## Behavior

### `/deployment` (no args) or `/deployment status`

```bash
gh run list --workflow=cd.yml --repo runno-ai/chatnut --limit 5 \
  --json status,conclusion,headBranch,displayTitle,createdAt,url \
  | python3 -m json.tool
```

Display as a table: branch, status, conclusion, created_at, URL.

### `/deployment logs`

```bash
RUN_ID=$(gh run list --workflow=cd.yml --repo runno-ai/chatnut --limit 1 \
  --json databaseId --jq '.[0].databaseId')
gh run view "$RUN_ID" --repo runno-ai/chatnut --log
```

### `/deployment trigger`

```bash
BRANCH=$(git branch --show-current)
# Confirm with user, then:
gh workflow run cd.yml --repo runno-ai/chatnut \
  --ref "$BRANCH" \
  --field branch="$BRANCH"
echo "CD workflow triggered on $BRANCH"
```

## Output Format

Report for each run:
- Status (queued / in_progress / completed)
- Conclusion (success / failure / cancelled)
- Branch and version being published
- Link to run URL
- Time since triggered
