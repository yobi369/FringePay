"""Provider construction and configuration validation."""

import hmac
from urllib.parse import parse_qs, urlsplit

from fringepay.config import Settings
from fringepay.pii import PhoneNumberCipher
from fringepay.providers import PaymentProvider, SandboxProvider


def validate_provider_settings(settings: Settings) -> None:
    """Fail fast when the selected adapter cannot be safely configured."""
    if settings.environment == "production":
        if not settings.database_url.startswith("postgresql+asyncpg://"):
            raise ValueError("production requires a PostgreSQL async database URL")
        PhoneNumberCipher(settings.pii_encryption_key, required=True)
    if settings.default_provider == "sandbox":
        return
    if settings.default_provider != "daraja":
        raise ValueError(f"unsupported payment provider: {settings.default_provider}")
    if settings.daraja_environment != "sandbox":
        raise ValueError("Daraja live environment is disabled in this release")
    required = {
        "consumer key": settings.daraja_consumer_key,
        "consumer secret": settings.daraja_consumer_secret,
        "business shortcode": settings.daraja_shortcode,
        "Lipa Na M-Pesa passkey": settings.daraja_passkey,
        "callback URL": settings.daraja_callback_url,
        "callback secret": settings.daraja_callback_secret,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise ValueError(f"missing Daraja configuration: {', '.join(missing)}")
    if len(settings.daraja_callback_secret) < 32:
        raise ValueError("Daraja callback secret must be at least 32 characters")
    if not settings.daraja_callback_url.startswith("https://"):
        raise ValueError("Daraja callback URL must use HTTPS")
    callback_tokens = parse_qs(urlsplit(settings.daraja_callback_url).query).get("token", [])
    if len(callback_tokens) != 1 or not hmac.compare_digest(
        callback_tokens[0], settings.daraja_callback_secret
    ):
        raise ValueError("Daraja callback URL token must match the configured callback secret")


def build_provider(settings: Settings) -> PaymentProvider:
    """Build the configured provider adapter without enabling live rails."""
    validate_provider_settings(settings)
    if settings.default_provider == "sandbox":
        return SandboxProvider()
    from fringepay.daraja import DarajaProvider

    return DarajaProvider(settings)
