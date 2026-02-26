from __future__ import annotations

import httpx

from ..config import settings
from ..schema import ToolRun


class SecurityMCP:
    def __init__(self):
        self.base = settings.mcp_security_url.rstrip("/")

    async def run_scans(self, repo_url: str, ref: str) -> ToolRun:
        async with httpx.AsyncClient(timeout=300) as client:
            r = await client.post(f"{self.base}/scan", json={"repo_url": repo_url, "ref": ref})
            ok = 200 <= r.status_code < 300
            data = r.json() if ok else {}
            return ToolRun(
                tool="security",
                action="scan",
                ok=ok and bool(data.get("ok", False)),
                meta={"status": r.status_code, "ref": ref},
                stdout=data.get("stdout"),
                stderr=data.get("stderr"),
            )
