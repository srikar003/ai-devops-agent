from pydantic import BaseModel
import os


class Settings(BaseModel):
    security_cmd_timeout_seconds: int = int(os.getenv("SECURITY_CMD_TIMEOUT_SECONDS", "1200"))
    security_retry_attempts: int = int(os.getenv("SECURITY_RETRY_ATTEMPTS", "3"))


settings = Settings()
