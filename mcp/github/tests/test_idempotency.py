from __future__ import annotations

import unittest
import importlib

try:
    github_main = importlib.import_module("mcp.github.main")
    import_error: Exception | None = None
except Exception as exc:  # noqa: BLE001
    github_main = None
    import_error = exc


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | list, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.headers: dict[str, str] = {}

    def json(self):
        return self._payload


class IdempotencyTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipIf(github_main is None, f"mcp.github.main import failed: {import_error}")
    async def test_post_comment_returns_deduped_when_marker_exists(self) -> None:
        original_request = github_main._request_with_retry
        original_token = github_main.GITHUB_TOKEN
        github_main.GITHUB_TOKEN = "token"
        calls: list[tuple[str, str]] = []
        marker = github_main._idempotency_marker("abc123")

        async def fake_request(method: str, url: str, *, headers_in: dict[str, str], json_body=None):
            calls.append((method, url))
            if method == "GET":
                return FakeResponse(
                    200,
                    [{"id": 99, "body": f"already posted\n\n{marker}"}],
                )
            return FakeResponse(201, {"id": 100})

        github_main._request_with_retry = fake_request
        try:
            result = await github_main.do_post_comment(
                owner="o",
                repo="r",
                pr=1,
                body="hello",
                idempotency_key="abc123",
            )
            self.assertTrue(result["ok"])
            self.assertTrue(result["deduped"])
            self.assertEqual(99, result["id"])
            self.assertEqual(1, len(calls))
            self.assertEqual("GET", calls[0][0])
        finally:
            github_main._request_with_retry = original_request
            github_main.GITHUB_TOKEN = original_token

    @unittest.skipIf(github_main is None, f"mcp.github.main import failed: {import_error}")
    async def test_set_commit_status_returns_deduped_when_latest_matches(self) -> None:
        original_request = github_main._request_with_retry
        original_token = github_main.GITHUB_TOKEN
        github_main.GITHUB_TOKEN = "token"
        calls: list[tuple[str, str]] = []

        async def fake_request(method: str, url: str, *, headers_in: dict[str, str], json_body=None):
            calls.append((method, url))
            if method == "GET":
                payload = {
                    "statuses": [
                        {
                            "context": "ai-devops-agent",
                            "state": "pending",
                            "description": "running",
                            "target_url": "",
                        }
                    ]
                }
                return FakeResponse(200, payload)
            return FakeResponse(201, {"ok": True})

        github_main._request_with_retry = fake_request
        try:
            result = await github_main.do_set_commit_status(
                owner="o",
                repo="r",
                sha="abc",
                state="pending",
                context="ai-devops-agent",
                description="running",
                target_url=None,
            )
            self.assertTrue(result["ok"])
            self.assertTrue(result["deduped"])
            self.assertEqual(1, len(calls))
            self.assertEqual("GET", calls[0][0])
        finally:
            github_main._request_with_retry = original_request
            github_main.GITHUB_TOKEN = original_token
