"""Runtime configuration with safe development defaults."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: str = "development"
    api_prefix: str = "/v1"
    database_url: str = "sqlite+aiosqlite:///./fringepay.db"
    sandbox_webhook_secret: str | None = None
    webhook_tolerance_seconds: int = 300
    pii_encryption_key: str | None = None
    default_provider: str = "sandbox"
    daraja_environment: str = "sandbox"
    daraja_consumer_key: str | None = None
    daraja_consumer_secret: str | None = None
    daraja_shortcode: str | None = None
    daraja_passkey: str | None = None
    daraja_callback_url: str | None = None
    daraja_transaction_type: str = "CustomerPayBillOnline"

    model_config = SettingsConfigDict(
        env_prefix="FRINGEPAY_",
        env_file=".env",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
