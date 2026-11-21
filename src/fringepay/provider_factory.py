"""Provider construction and configuration validation."""

from fringepay.config import Settings
from fringepay.providers import PaymentProvider, SandboxProvider


def validate_provider_settings(settings: Settings) -> None:
    """Fail fast when the selected adapter cannot be safely configured."""
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
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise ValueError(f"missing Daraja configuration: {', '.join(missing)}")
    if not settings.daraja_callback_url.startswith("https://"):
        raise ValueError("Daraja callback URL must use HTTPS")


def build_provider(settings: Settings) -> PaymentProvider:
    """Build the configured provider adapter without enabling live rails."""
    validate_provider_settings(settings)
    if settings.default_provider == "sandbox":
        return SandboxProvider()
    from fringepay.daraja import DarajaProvider

    return DarajaProvider(settings)
