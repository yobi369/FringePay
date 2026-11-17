"""Runtime configuration with safe development defaults."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: str = "development"
    api_prefix: str = "/v1"
    database_url: str = "sqlite+aiosqlite:///./fringepay.db"

    model_config = SettingsConfigDict(
        env_prefix="FRINGEPAY_",
        env_file=".env",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
