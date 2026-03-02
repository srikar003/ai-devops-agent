from __future__ import annotations

import asyncio
import json
import logging
from functools import partial
from typing import Any, Dict

from langchain_mcp_adapters.client import MultiServerMCPClient

from ..config import settings
from ..utils.retry import retry_async

logger = logging.getLogger(__name__)


class MCPGatewayClient:
    def __init__(self, servers: Dict[str, str]):
        self._servers = servers
        self._clients: Dict[str, MultiServerMCPClient] = {}

    async def invoke(
        self,
        server: str,
        tool_name: str,
        payload: Dict[str, Any],
        *,
        write_operation: bool = False,
    ) -> Dict[str, Any]:
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

        client = self.get_or_create_client(server, url)

        retry_ctx: Dict[str, Any] = {}
        retry_attempts = (
            max(1, settings.mcp_write_retry_attempts)
            if write_operation
            else max(1, settings.retry_attempts)
        )
        out = await retry_async(
            partial(self.invoke_tool_once, client, server, tool_name, payload),
            attempts=retry_attempts,
            base_delay_seconds=max(0.0, settings.retry_base_delay_seconds),
            max_delay_seconds=max(0.0, settings.retry_max_delay_seconds),
            jitter_seconds=max(0.0, settings.retry_jitter_seconds),
            context=retry_ctx,
        )
        logger.info(
            "MCP invoke done server=%s tool=%s attempts=%s elapsed_ms=%s result_keys=%s",
            server,
            tool_name,
            retry_ctx.get("attempts", 1),
            retry_ctx.get("elapsed_ms", 0),
            sorted(out.keys()) if isinstance(out, dict) else [],
        )
        return out

    async def invoke_tool_once(
        self,
        client: MultiServerMCPClient,
        server: str,
        tool_name: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        tools = await client.get_tools()
        tool = next((t for t in tools if t.name == tool_name), None)
        if tool is None:
            available = ", ".join(sorted(t.name for t in tools))
            raise ValueError(
                f"Tool '{tool_name}' not found on server '{server}'. Available: {available}"
            )
        result = await asyncio.wait_for(
            tool.ainvoke(payload),
            timeout=max(1.0, settings.mcp_tool_timeout_seconds),
        )
        return self.coerce_to_dict(result)

    def get_or_create_client(self, server: str, url: str) -> MultiServerMCPClient:
        client = self._clients.get(server)
        if client is not None:
            return client
        client = MultiServerMCPClient(
            {
                server: {
                    "transport": "streamable_http",
                    "url": url,
                }
            }
        )
        self._clients[server] = client
        return client

    def coerce_to_dict(self, value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            # Common MCP adapter envelope:
            # {"content":[{"type":"text","text":"{...json...}"}], "isError":false}
            if "content" in value and isinstance(value.get("content"), list):
                parsed = self.extract_from_content_blocks(value.get("content"))
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
            parsed = self.extract_from_content_blocks(value)
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
            parsed = self.extract_from_content_blocks(content)
            if parsed is not None:
                return parsed
        logger.warning("MCP response coercion fallback type=%s", type(value).__name__)
        return {"result": value}

    def extract_from_content_blocks(self, blocks: Any) -> Dict[str, Any] | None:
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
