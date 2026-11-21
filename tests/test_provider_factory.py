from cryptography.fernet import Fernet
import pytest

from fringepay.config import Settings
from fringepay.provider_factory import validate_provider_settings


def production_settings(**overrides) -> Settings:
    values = {
        "environment": "production",
        "database_url": "postgresql+asyncpg://user:secret@db.example.test/fringepay",
        "pii_encryption_key": Fernet.generate_key().decode("ascii"),
        "default_provider": "sandbox",
    }
    values.update(overrides)
    return Settings(**values)


def test_production_rejects_non_postgresql_database() -> None:
    settings = production_settings(database_url="sqlite+aiosqlite:///./fringepay.db")
    with pytest.raises(ValueError, match="PostgreSQL"):
        validate_provider_settings(settings)


def test_production_requires_a_valid_pii_encryption_key() -> None:
    settings = production_settings(pii_encryption_key=None)
    with pytest.raises(ValueError, match="required in production"):
        validate_provider_settings(settings)


def test_production_rejects_invalid_fernet_key() -> None:
    settings = production_settings(pii_encryption_key="not-a-fernet-key")
    with pytest.raises(ValueError, match="valid Fernet key"):
        validate_provider_settings(settings)


def test_production_accepts_postgresql_and_valid_pii_key() -> None:
    validate_provider_settings(production_settings())


def test_daraja_requires_callback_secret_in_url_and_configuration() -> None:
    secret = "a" * 48
    settings = production_settings(
        environment="development",
        default_provider="daraja",
        daraja_environment="sandbox",
        daraja_consumer_key="sandbox-key",
        daraja_consumer_secret="sandbox-secret",
        daraja_shortcode="174379",
        daraja_passkey="sandbox-passkey",
        daraja_callback_url=(
            "https://payments.example.test/v1/webhooks/daraja?token=" + secret
        ),
        daraja_callback_secret=secret,
    )
    validate_provider_settings(settings)
