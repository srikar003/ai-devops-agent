from __future__ import annotations
import boto3
import json
import logging
from functools import partial
from botocore.exceptions import BotoCoreError, ClientError
from botocore.config import Config

from ..config import settings
from ..utils.retry import retry_sync

logger = logging.getLogger(__name__)


class BedrockLLM:
    """
    Minimal Bedrock invoke wrapper for text generation.
    You can swap payloads depending on model provider (Anthropic, etc.).
    """

    def __init__(self):
        self.client = boto3.client(
            "bedrock-runtime",
            region_name=settings.aws_region,
            config=Config(
                retries={
                    "mode": "adaptive",
                    "max_attempts": max(2, settings.retry_attempts),
                },
                connect_timeout=5,
                read_timeout=max(10, int(settings.mcp_tool_timeout_seconds)),
            ),
        )
        self.model_id = settings.bedrock_model_id

    def invoke_text(self, prompt: str) -> str:
        if not self.model_id:
            raise RuntimeError("BEDROCK_MODEL_ID is not set")

        # This payload works for many Anthropic models on Bedrock using Messages API style.
        # Some accounts/models may need minor payload tweaks.
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1800,
            "temperature": 0.2,
            "messages": [{"role": "user", "content": prompt}],
        }

        retry_ctx: dict[str, object] = {}
        data = retry_sync(
            partial(self.invoke_model_once, body),
            attempts=max(1, settings.retry_attempts),
            base_delay_seconds=max(0.0, settings.retry_base_delay_seconds),
            max_delay_seconds=max(0.0, settings.retry_max_delay_seconds),
            jitter_seconds=max(0.0, settings.retry_jitter_seconds),
            should_retry=self.is_transient_bedrock_error,
            context=retry_ctx,
        )
        logger.info(
            "Bedrock invoke completed attempts=%s elapsed_ms=%s",
            retry_ctx.get("attempts", 1),
            retry_ctx.get("elapsed_ms", 0),
        )
        # For Anthropic, text can appear in content blocks:
        # {"content":[{"type":"text","text":"..."}], ...}
        content = data.get("content", [])
        if content and isinstance(content, list) and "text" in content[0]:
            return content[0]["text"]
        return json.dumps(data)

    def invoke_model_once(self, body: dict) -> dict:
        resp = self.client.invoke_model(
            modelId=self.model_id,
            body=json.dumps(body).encode("utf-8"),
            contentType="application/json",
            accept="application/json",
        )
        return json.loads(resp["body"].read())

    def is_transient_bedrock_error(self, exc: Exception) -> bool:
        if isinstance(exc, BotoCoreError):
            return True
        if isinstance(exc, ClientError):
            code = str(exc.response.get("Error", {}).get("Code", ""))
            transient_codes = {
                "ThrottlingException",
                "TooManyRequestsException",
                "ServiceUnavailableException",
                "InternalServerException",
                "ModelNotReadyException",
                "ModelTimeoutException",
            }
            if code in transient_codes:
                return True
        msg = str(exc).lower()
        return any(
            token in msg
            for token in [
                "timeout",
                "timed out",
                "throttl",
                "too many requests",
                "service unavailable",
            ]
        )
