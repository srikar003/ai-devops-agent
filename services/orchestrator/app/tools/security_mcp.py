from __future__ import annotations

import logging

from ..config import settings
from ..schema import ToolRun
from .mcp_gateway_client import MCPGatewayClient

logger = logging.getLogger(__name__)


class SecurityMCP:
    def __init__(self):
        self.client = MCPGatewayClient({"security": settings.mcp_security_url})

    async def run_scans(self, repo_url: str, ref: str) -> ToolRun:
        logger.info("SecurityMCP.run_scans repo_url=%s ref=%s", repo_url, ref)
        data = await self.client.invoke(
            "security",
            "security_scan",
            {"repo_url": repo_url, "ref": ref},
            write_operation=False,
        )
        ok = bool(data.get("ok", False))
        logger.info("SecurityMCP.run_scans done ok=%s keys=%s", ok, sorted(data.keys()))
        return ToolRun(
            tool="security",
            action="scan",
            ok=ok,
            meta={"ref": ref},
            stdout=data.get("stdout"),
            stderr=data.get("stderr"),
        )
