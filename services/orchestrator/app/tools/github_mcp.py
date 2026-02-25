from __future__ import annotations

from typing import Any, Dict, Optional
import httpx

from ..schema import ToolRun


class GitHubMCP:
    def __init__(self, base_url: str = "http://mcp_github:7001"):
        self.base_url = base_url.rstrip("/")

    async def get_pr_context(
        self, owner: str, repo: str, pr_number: int
    ) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(
                f"{self.base_url}/pr",
                params={"owner": owner, "repo": repo, "pr": pr_number},
            )
            r.raise_for_status()
            return r.json()

    async def post_comment(
        self, owner: str, repo: str, pr_number: int, body: str
    ) -> ToolRun:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"{self.base_url}/comment",
                json={"owner": owner, "repo": repo, "pr": pr_number, "body": body},
            )
            ok = 200 <= r.status_code < 300
            return ToolRun(
                tool="github",
                action="comment",
                ok=ok,
                meta={"status": r.status_code},
                stdout=r.text if ok else None,
                stderr=None if ok else r.text,
            )

    async def set_commit_status(
        self,
        owner: str,
        repo: str,
        sha: str,
        state: str,  # "error" | "failure" | "pending" | "success"
        context: str = "ai-devops-agent",
        description: Optional[str] = None,
        target_url: Optional[str] = None,
    ) -> ToolRun:
        """
        Uses the GitHub Statuses API via MCP endpoint /status (PAT-friendly).
        """
        async with httpx.AsyncClient(timeout=60) as client:
            payload: Dict[str, Any] = {
                "owner": owner,
                "repo": repo,
                "sha": sha,
                "state": state,
                "context": context,
                "description": description,
                "target_url": target_url,
            }
            r = await client.post(f"{self.base_url}/status", json=payload)
            ok = 200 <= r.status_code < 300
            return ToolRun(
                tool="github",
                action="status",
                ok=ok,
                meta={"status": r.status_code, "state": state, "context": context},
                stdout=r.text if ok else None,
                stderr=None if ok else r.text,
            )
