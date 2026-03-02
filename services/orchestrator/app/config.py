from pydantic import BaseModel
import os


class Settings(BaseModel):
    mcp_github_url: str = os.getenv("MCP_GITHUB_URL", "http://localhost:7001/mcp")
    mcp_ci_url: str = os.getenv("MCP_CI_URL", "http://localhost:7002/mcp")
    mcp_security_url: str = os.getenv("MCP_SECURITY_URL", "http://localhost:7003/mcp")

    aws_region: str = os.getenv("AWS_REGION", "us-east-1")
    bedrock_model_id: str = os.getenv("BEDROCK_MODEL_ID", "")
    retry_attempts: int = int(os.getenv("RETRY_ATTEMPTS", "3"))
    retry_base_delay_seconds: float = float(os.getenv("RETRY_BASE_DELAY_SECONDS", "0.5"))
    retry_max_delay_seconds: float = float(os.getenv("RETRY_MAX_DELAY_SECONDS", "5.0"))
    retry_jitter_seconds: float = float(os.getenv("RETRY_JITTER_SECONDS", "0.2"))
    graph_max_total_node_calls: int = int(os.getenv("GRAPH_MAX_TOTAL_NODE_CALLS", "100"))
    graph_max_calls_per_node: int = int(os.getenv("GRAPH_MAX_CALLS_PER_NODE", "5"))
    graph_recursion_limit: int = int(os.getenv("GRAPH_RECURSION_LIMIT", "80"))
    mcp_tool_timeout_seconds: float = float(os.getenv("MCP_TOOL_TIMEOUT_SECONDS", "120.0"))
    mcp_write_retry_attempts: int = int(os.getenv("MCP_WRITE_RETRY_ATTEMPTS", "2"))


settings = Settings()
