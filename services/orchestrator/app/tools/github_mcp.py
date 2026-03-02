from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ..config import settings
from ..schema import ToolRun
from .mcp_gateway_client import MCPGatewayClient

logger = logging.getLogger(__name__)


class GitHubMCP:
    def __init__(self):
        self.client = MCPGatewayClient({"github": settings.mcp_github_url})

    async def get_pr_context(
        self, owner: str, repo: str, pr_number: int
    ) -> Dict[str, Any]:
        logger.info(
            "GitHubMCP.get_pr_context owner=%s repo=%s pr=%s", owner, repo, pr_number
        )
        data = await self.client.invoke(
            "github",
            "github_get_pr_context",
            {"owner": owner, "repo": repo, "pr": pr_number},
            write_operation=False,
            timeout_seconds=settings.mcp_github_timeout_seconds,
        )
        logger.info("GitHubMCP.get_pr_context done keys=%s", sorted(data.keys()))
        return data

    async def post_comment(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        body: str,
        idempotency_key: str | None = None,
    ) -> ToolRun:
        logger.info(
            "GitHubMCP.post_comment owner=%s repo=%s pr=%s", owner, repo, pr_number
        )
        data = await self.client.invoke(
            "github",
            "github_post_comment",
            {
                "owner": owner,
                "repo": repo,
                "pr": pr_number,
                "body": body,
                "idempotency_key": idempotency_key,
            },
            write_operation=True,
            timeout_seconds=settings.mcp_github_timeout_seconds,
        )
        ok = bool(data.get("ok", False))
        logger.info(
            "GitHubMCP.post_comment done ok=%s keys=%s", ok, sorted(data.keys())
        )
        return ToolRun(
            tool="github",
            action="comment",
            ok=ok,
            meta={
                "comment_id": data.get("id"),
                "deduped": bool(data.get("deduped", False)),
            },
            stdout=str(data) if ok else None,
            stderr=None if ok else str(data),
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
        logger.info(
            "GitHubMCP.set_commit_status owner=%s repo=%s sha=%s state=%s",
            owner,
            repo,
            sha[:7] if sha else "",
            state,
        )
        payload: Dict[str, Any] = {
            "owner": owner,
            "repo": repo,
            "sha": sha,
            "state": state,
            "context": context,
            "description": description,
            "target_url": target_url,
        }
        data = await self.client.invoke(
            "github",
            "github_set_commit_status",
            payload,
            write_operation=True,
            timeout_seconds=settings.mcp_github_timeout_seconds,
        )
        ok = bool(data.get("ok", False))
        logger.info(
            "GitHubMCP.set_commit_status done ok=%s keys=%s", ok, sorted(data.keys())
        )
        return ToolRun(
            tool="github",
            action="status",
            ok=ok,
            meta={
                "state": state,
                "context": context,
                "deduped": bool(data.get("deduped", False)),
            },
            stdout=str(data) if ok else None,
            stderr=None if ok else str(data),
        )
