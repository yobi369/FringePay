"""Runtime configuration with safe development defaults."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: str = "development"
    api_prefix: str = "/v1"
    database_url: str = "sqlite+aiosqlite:///./fringepay.db"
    sandbox_webhook_secret: str | None = None
    webhook_tolerance_seconds: int = 300

    model_config = SettingsConfigDict(
        env_prefix="FRINGEPAY_",
        env_file=".env",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
