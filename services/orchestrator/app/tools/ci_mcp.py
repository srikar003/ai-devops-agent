from __future__ import annotations

import httpx

from ..config import settings
from ..schema import ToolRun


class CIMCP:
    def __init__(self):
        self.base = settings.mcp_ci_url.rstrip("/")

    async def run_ci(self, repo_url: str, ref: str) -> ToolRun:
        tr = ToolRun(tool="ci", action="run", ok=False)
        async with httpx.AsyncClient(timeout=3000) as client:
            r = await client.post(f"{self.base}/run", json={"repo_url": repo_url, "ref": ref})
            data = (
                r.json()
                if r.headers.get("content-type", "").startswith("application/json")
                else {}
            )
            tr.meta["status"] = r.status_code

        tr.meta["ref"] = ref
        tr.ok = bool(data.get("ok", False)) and (200 <= r.status_code < 300)
        tr.stdout = data.get("stdout")
        tr.stderr = data.get("stderr")
        tr.meta["summary"] = data.get("summary", {})
        return tr
