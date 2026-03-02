# AI DevOps Multi-Agent PR Reviewer

AI-driven pull request review system with deterministic CI/security checks and LLM-based analysis, orchestrated by LangGraph.

## What This System Does

Given a GitHub PR (`owner`, `repo`, `pr_number`), the orchestrator:

1. Fetches PR context (title, body, files, diff) from GitHub MCP.
2. Sets commit status to `pending`.
3. Runs CI and security scans in parallel.
4. Runs review agents in parallel:
   - triage
   - code review
   - security review
5. Ranks findings by severity.
6. Composes and posts a PR comment.
7. Sets final commit status (`success` or `failure`).

## Services

| Service | Port | Purpose |
|---|---:|---|
| `orchestrator` | 8000 | LangGraph workflow + API |
| `mcp_github` | 7001 | GitHub tool operations |
| `mcp_ci` | 7002 | CI execution over repo clone |
| `mcp_security` | 7003 | Semgrep-based scanning |
| `postgres` | 5432 | LangGraph checkpoint memory |

## Major Reliability and Production Updates Implemented

### 1. Retry framework

- Central retry utility in `services/orchestrator/app/utils/retry.py`.
- Exponential backoff + jitter.
- Transient error filtering.
- Retry telemetry context (`attempts`, `elapsed_ms`, `last_error`).

### 2. MCP timeout and retry hardening

- `MCPGatewayClient` retries transient failures and enforces timeouts.
- Per-service timeout controls:
  - `MCP_GITHUB_TIMEOUT_SECONDS`
  - `MCP_CI_TIMEOUT_SECONDS`
  - `MCP_SECURITY_TIMEOUT_SECONDS`
- CI/security use long timeout windows to avoid cancellation of legitimate long-running jobs.

### 3. Idempotency for GitHub writes

- Comment posting deduped with idempotency marker.
- Commit status updates deduped when latest status already matches.
- Prevents duplicate side effects during retries.

### 4. Loop/runaway protection

- Node call tracking in graph state.
- Guard logic in `services/orchestrator/app/graph_guard.py`.
- Enforces:
  - max total node calls
  - max calls per node
- Independent from LangGraph recursion limit.

### 5. Graph checkpoint memory in Postgres

- LangGraph Postgres checkpoint saver wired in orchestrator lifespan.
- Uses `DATABASE_URL`.
- Thread-scoped persistence via `thread_id` in `/run`.
- Default thread id fallback: `owner/repo#pr_number`.

### 6. Config standardization

- Orchestrator config: `services/orchestrator/app/config.py`.
- MCP service configs:
  - `mcp/ci/config.py`
  - `mcp/security/config.py`
  - `mcp/github/config.py`
- Runtime values are loaded from env with sensible defaults.

### 7. Testing coverage added

- Retry tests.
- Graph guard tests.
- GitHub idempotency tests.

See `TESTING.md` for exact commands.

## API Endpoints (Orchestrator)

### POST `/run`

Request:

```json
{
  "owner": "your-org",
  "repo": "your-repo",
  "pr_number": 123,
  "thread_id": "optional-thread-id"
}
```

Response includes:

- `final_comment`
- `findings`
- `tool_runs`
- `node_calls`
- `thread_id`

### GET `/graph`

Returns graph image (`image/png`) generated from LangGraph Mermaid rendering.

## Environment Variables

### Orchestrator

- `MCP_GITHUB_URL`
- `MCP_CI_URL`
- `MCP_SECURITY_URL`
- `AWS_REGION`
- `BEDROCK_MODEL_ID`
- `DATABASE_URL`
- `RETRY_ATTEMPTS`
- `RETRY_BASE_DELAY_SECONDS`
- `RETRY_MAX_DELAY_SECONDS`
- `RETRY_JITTER_SECONDS`
- `GRAPH_MAX_TOTAL_NODE_CALLS`
- `GRAPH_MAX_CALLS_PER_NODE`
- `GRAPH_RECURSION_LIMIT`
- `MCP_TOOL_TIMEOUT_SECONDS`
- `MCP_GITHUB_TIMEOUT_SECONDS`
- `MCP_CI_TIMEOUT_SECONDS`
- `MCP_SECURITY_TIMEOUT_SECONDS`
- `MCP_WRITE_RETRY_ATTEMPTS`

### MCP GitHub

- `GITHUB_TOKEN`
- `GITHUB_HTTP_TIMEOUT_SECONDS`
- `GITHUB_RETRY_ATTEMPTS`

### MCP CI

- `CI_RETRY_ATTEMPTS`

### MCP Security

- `SECURITY_CMD_TIMEOUT_SECONDS`
- `SECURITY_RETRY_ATTEMPTS`

## Run with Docker Compose

```powershell
docker compose -f infra/docker-compose.yml up --build
```

Trigger run:

```powershell
curl -X POST http://localhost:8000/run `
  -H "Content-Type: application/json" `
  -d "{\"owner\":\"your-org\",\"repo\":\"your-repo\",\"pr_number\":1}"
```

Fetch graph image:

```powershell
curl http://localhost:8000/graph --output graph.png
```

## Notes

- If checkpoint initialization fails with psycopg errors, ensure orchestrator dependencies are rebuilt (`psycopg[binary]` is required).
- Recursion limit must be high enough for normal graph execution path. Keep `GRAPH_RECURSION_LIMIT` above trivial values like `5`.
