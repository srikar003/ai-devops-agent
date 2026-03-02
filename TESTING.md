# Testing Guide

## Prerequisites

Use Python 3.11+ and install dependencies for the components you want to test.

### Orchestrator tests

```powershell
pip install -r services/orchestrator/requirements.txt
```

### MCP GitHub tests

```powershell
pip install -r services/orchestrator/requirements.txt
```

`mcp/github/main.py` imports `httpx`. If missing, idempotency tests are skipped by design.

## Run tests

### Run orchestrator unit tests

```powershell
python -m unittest discover -s services/orchestrator/tests -p "test_*.py" -v
```

Coverage includes:

- retry behavior (`test_retry.py`)
- graph guard behavior (`test_graph_guard.py`)

### Run MCP GitHub idempotency tests

```powershell
python -m unittest discover -s mcp/github/tests -p "test_*.py" -v
```

Coverage includes:

- comment idempotency dedupe
- commit status idempotency dedupe

## Notes

- If MCP GitHub tests show `skipped ... No module named 'httpx'`, install dependencies first.
- Tests are pure unit tests and do not call external services.
- For containerized verification, rebuild affected service after dependency or config changes:

```powershell
docker compose -f infra/docker-compose.yml build orchestrator mcp_github mcp_ci mcp_security
docker compose -f infra/docker-compose.yml up -d
```
