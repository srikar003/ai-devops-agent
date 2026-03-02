from __future__ import annotations

import logging

from ..config import settings
from ..schema import ToolRun
from .mcp_gateway_client import MCPGatewayClient

logger = logging.getLogger(__name__)


class CIMCP:
    def __init__(self):
        self.client = MCPGatewayClient({"ci": settings.mcp_ci_url})

    async def run_ci(self, repo_url: str, ref: str) -> ToolRun:
        logger.info("CIMCP.run_ci repo_url=%s ref=%s", repo_url, ref)
        tr = ToolRun(tool="ci", action="run", ok=False)
        data = await self.client.invoke(
            "ci",
            "ci_run",
            {"repo_url": repo_url, "ref": ref},
            write_operation=False,
        )

        tr.meta["ref"] = ref
        tr.ok = bool(data.get("ok", False))
        tr.stdout = data.get("stdout")
        tr.stderr = data.get("stderr")
        tr.meta["summary"] = data.get("summary", {})
        logger.info(
            "CIMCP.run_ci done ok=%s summary_keys=%s",
            tr.ok,
            sorted((tr.meta.get("summary") or {}).keys()),
        )
        return tr
