from pydantic import BaseModel
import os


class Settings(BaseModel):
    github_token: str = os.getenv("GITHUB_TOKEN", "")
    github_http_timeout_seconds: float = float(os.getenv("GITHUB_HTTP_TIMEOUT_SECONDS", "60"))
    github_retry_attempts: int = int(os.getenv("GITHUB_RETRY_ATTEMPTS", "3"))
    github_transient_status_codes: list[int] = [408, 409, 425, 429, 500, 502, 503, 504]


settings = Settings()
