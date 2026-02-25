from pydantic import BaseModel
import os


class Settings(BaseModel):
    mcp_github_url: str = os.getenv("MCP_GITHUB_URL", "http://localhost:7001")
    mcp_ci_url: str = os.getenv("MCP_CI_URL", "http://localhost:7002")
    mcp_security_url: str = os.getenv("MCP_SECURITY_URL", "http://localhost:7003")

    aws_region: str = os.getenv("AWS_REGION", "us-east-1")
    bedrock_model_id: str = os.getenv("BEDROCK_MODEL_ID", "")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    database_url: str = os.getenv("DATABASE_URL", "")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")


settings = Settings()
