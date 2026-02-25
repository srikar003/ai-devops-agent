from __future__ import annotations
import httpx
from ..config import settings
from ..schema import ToolRun


class GitHubMCP:
    def __init__(self):
        self.base = settings.mcp_github_url

    async def get_pr_context(self, owner: str, repo: str, pr_number: int):
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(f"{self.base}/pr", params={"owner": owner, "repo": repo, "pr": pr_number})
            r.raise_for_status()
            return r.json()

    async def post_comment(self, owner: str, repo: str, pr_number: int, body: str) -> ToolRun:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(f"{self.base}/comment", json={"owner": owner, "repo": repo, "pr": pr_number, "body": body})
            ok = r.status_code // 100 == 2
            return ToolRun(tool="github", action="comment", ok=ok, meta={"status": r.status_code}, stdout=r.text if ok else None, stderr=None if ok else r.text)