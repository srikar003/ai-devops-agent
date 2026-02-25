from __future__ import annotations
import boto3
import json
from ..config import settings


class BedrockLLM:
    """
    Minimal Bedrock invoke wrapper for text generation.
    You can swap payloads depending on model provider (Anthropic, etc.).
    """
    def __init__(self):
        self.client = boto3.client("bedrock-runtime", region_name=settings.aws_region)
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

        resp = self.client.invoke_model(
            modelId=self.model_id,
            body=json.dumps(body).encode("utf-8"),
            contentType="application/json",
            accept="application/json",
        )
        data = json.loads(resp["body"].read())
        # For Anthropic, text can appear in content blocks:
        # {"content":[{"type":"text","text":"..."}], ...}
        content = data.get("content", [])
        if content and isinstance(content, list) and "text" in content[0]:
            return content[0]["text"]
        return json.dumps(data)