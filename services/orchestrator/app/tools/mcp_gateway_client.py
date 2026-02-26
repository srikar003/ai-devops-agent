from __future__ import annotations

import json
import logging
from typing import Any, Dict

from langchain_mcp_adapters.client import MultiServerMCPClient

logger = logging.getLogger(__name__)


class MCPGatewayClient:
    def __init__(self, servers: Dict[str, str]):
        self._servers = servers

    async def invoke(self, server: str, tool_name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = self._servers.get(server)
        if not url:
            raise ValueError(f"Unknown MCP server '{server}'")

        logger.info(
            "MCP invoke start server=%s tool=%s url=%s payload_keys=%s",
            server,
            tool_name,
            url,
            sorted(payload.keys()),
        )

        client = MultiServerMCPClient(
            {
                server: {
                    "transport": "streamable_http",
                    "url": url,
                }
            }
        )
        tools = await client.get_tools()
        tool = next((t for t in tools if t.name == tool_name), None)
        if tool is None:
            available = ", ".join(sorted(t.name for t in tools))
            raise ValueError(
                f"Tool '{tool_name}' not found on server '{server}'. Available: {available}"
            )
        result = await tool.ainvoke(payload)
        out = self._coerce_to_dict(result)
        logger.info(
            "MCP invoke done server=%s tool=%s result_keys=%s",
            server,
            tool_name,
            sorted(out.keys()) if isinstance(out, dict) else [],
        )
        return out

    def _coerce_to_dict(self, value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            # Common MCP adapter envelope:
            # {"content":[{"type":"text","text":"{...json...}"}], "isError":false}
            if "content" in value and isinstance(value.get("content"), list):
                parsed = self._extract_from_content_blocks(value.get("content"))
                if parsed is not None:
                    return parsed
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                return {"result": value}
        if isinstance(value, list):
            parsed = self._extract_from_content_blocks(value)
            if parsed is not None:
                return parsed
            return {"items": value}
        content = getattr(value, "content", None)
        if isinstance(content, str):
            try:
                parsed = json.loads(content)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                return {"result": content}
        if isinstance(content, list):
            parsed = self._extract_from_content_blocks(content)
            if parsed is not None:
                return parsed
        logger.warning("MCP response coercion fallback type=%s", type(value).__name__)
        return {"result": value}

    def _extract_from_content_blocks(self, blocks: Any) -> Dict[str, Any] | None:
        if not isinstance(blocks, list):
            return None
        for block in blocks:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                text = block["text"]
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, dict):
                        return parsed
                except json.JSONDecodeError:
                    continue
        return None
