from pydantic import BaseModel
import os


class Settings(BaseModel):
    ci_retry_attempts: int = int(os.getenv("CI_RETRY_ATTEMPTS", "3"))


settings = Settings()
