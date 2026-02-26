# 🤖 AI DevOps Multi-Agent PR Reviewer

An AI-powered DevOps agent that automatically reviews GitHub Pull Requests using:

- ✅ Deterministic CI checks (install, audit, lint, test, build)
- ✅ Static security scanning (Semgrep)
- ✅ LLM-based code review and security reasoning
- ✅ Structured findings + severity ranking
- ✅ Automated PR comment generation
- ✅ Commit status gating (pending → success/failure)

## 🔧 Tech Stack

- **LangGraph**
- **FastAPI**
- **AWS Bedrock (Claude)**
- **Docker Compose**
- **Semgrep**
- **Nx / Node workspaces**
- **GitHub API**

---

# Integration Mode

The orchestrator currently integrates with service HTTP endpoints (not MCP transport).

- `mcp_github`: `/pr`, `/status`, `/comment`, `/check-run`
- `mcp_ci`: `/run`
- `mcp_security`: `/scan`

The `/mcp` endpoints may exist on services for future use, but they are not used by the orchestrator runtime flow.

---

# 🏆 Why This Project Matters

This is not a basic CI bot.

It is a:

> Multi-Agent AI DevOps System combining deterministic checks with LLM reasoning for automated PR governance.

It demonstrates:
- Agent orchestration
- Structured AI outputs
- DevOps automation
- Security integration
- Production-ready microservice architecture

---

# 🏗 Architecture

```
GitHub Pull Request
        ↓
AI DevOps Orchestrator (LangGraph)
        ↓
┌───────────────────┬───────────────────┬───────────────────┐
│ MCP GitHub        │ MCP CI            │ MCP Security      │
│ PR + Status       │ npm/nx/audit      │ Semgrep scan      │
└───────────────────┴───────────────────┴───────────────────┘
        ↓
LLM Agents (Code + Security + Ranking)
        ↓
PR Comment + Commit Status
```

---

# 🔄 Application Flow

## 1️⃣ Trigger

```bash
POST /run
{
  "owner": "your-username",
  "repo": "your-repo",
  "pr_number": 1
}
```

---

## 2️⃣ LangGraph Execution Pipeline

1. `fetch_pr`
2. `create_check_run` → sets commit status to **pending**
3. `run_ci`
4. `run_security`
5. `triage` (LLM summary)
6. `code_review` (LLM JSON findings)
7. `security_review`
8. `rank_findings`
9. `compose_comment`
10. `post_comment`
11. `complete_check_run` → success/failure

---

# 🧠 Design Principles

- Deterministic first, AI second
- Structured findings (not raw text)
- Policy-driven gating
- Microservice isolation
- Extensible multi-agent architecture

---

# 📦 Services

| Service         | Port | Description                          |
|----------------|------|--------------------------------------|
| Orchestrator  | 8000 | LangGraph multi-agent workflow       |
| MCP GitHub    | 7001 | GitHub API HTTP wrapper              |
| MCP CI        | 7002 | Deterministic CI runner (HTTP)       |
| MCP Security  | 7003 | Static security scanning (HTTP)      |

---

# ⚙️ Environment Variables

## Orchestrator

```
MCP_GITHUB_URL=http://mcp_github:7001
MCP_CI_URL=http://mcp_ci:7002
MCP_SECURITY_URL=http://mcp_security:7003

AWS_REGION=us-east-1
BEDROCK_MODEL_ID=anthropic.claude-3-5-haiku-20241022-v1:0

AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
```

---

## MCP GitHub

```
GITHUB_TOKEN=your_grained_personal_access_token
```

---

# 🐳 Run with Docker

```bash
docker compose up --build
```

Trigger a review:

```bash
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d '{"owner":"your-user","repo":"your-repo","pr_number":1}'
```

---

# 🔍 CI Behavior

The CI MCP performs:

- Git clone + checkout PR ref
- `npm ci`
- `npm audit` (policy-based)
- Nx detection
- `nx run-many -t lint --all`
- Optional test/build execution

Audit policy (configurable):
- Fail on **critical only** (recommended default)
- Report high vulnerabilities without failing

---

# 🔐 Security Behavior

The Security MCP:

- Clones repository
- Runs `semgrep --config auto`
- Returns structured scan output

The LLM security agent:
- Analyzes diff + scan output
- Generates security findings
- Provides remediation guidance

---

# 📊 Findings Model

All issues are converted into structured objects:

```json
{
  "type": "CODE_QUALITY | BUG_RISK | SECURITY | PERFORMANCE | TESTING | CI",
  "severity": "LOW | MEDIUM | HIGH | CRITICAL",
  "title": "Short summary",
  "file": "path/to/file",
  "line": 42,
  "details": "Explanation",
  "recommendation": "How to fix"
}
```

Findings are:
- Ranked by severity
- Grouped in PR comment
- Used for commit status gating

---

# 🚦 Commit Status Logic

| Condition | Status |
|-----------|--------|
| CRITICAL findings exist | ❌ failure |
| HIGH findings (if policy strict) | ❌ failure |
| Only MEDIUM/LOW findings | ✅ success |

---

# 🧩 Example PR Comment Output

```markdown
## 🤖 AI DevOps Review

### Summary
- Refactors auth module
- Updates dashboard imports

### Checks Run
- ci/run: ❌
- security/scan: ✅

### 🔴 CRITICAL
None

### 🟠 HIGH
- Lint error: @nx/dependency-checks (auth/package.json:8)
  Missing dependencies declared in package.json

### 🟡 MEDIUM
- 26 high vulnerabilities found via npm audit

### 🟢 LOW
- Angular template accessibility warnings
```

---

# 🚀 Roadmap

### 🔐 Phase 2 — Advanced Security Intelligence

- Add secrets scanning (Gitleaks)
- Integrate container/IaC scanning (Trivy)
- Normalize all tools into unified SECURITY findings
- Implement deterministic policy engine (fail on critical)
- Add allowlist + vulnerability metadata (CVE, fix version)


### 🖥 Phase 3 — Full Application Layer (React + Node + Postgres)

- Build Node API to persist PR runs and findings
- Store review history in Postgres
- Create React dashboard for visibility
- Provide filtering by repo, severity, status
- Enable re-run reviews + analytics tracking

---
