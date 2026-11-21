"""Provider construction from validated runtime configuration."""

from fringepay.config import Settings
from fringepay.providers import PaymentProvider, SandboxProvider


def build_provider(settings: Settings) -> PaymentProvider:
    """Build the configured provider adapter without enabling live rails."""
    if settings.default_provider == "sandbox":
        return SandboxProvider()
    if settings.default_provider == "daraja":
        from fringepay.daraja import DarajaProvider

        return DarajaProvider(settings)
    raise ValueError(f"unsupported payment provider: {settings.default_provider}")
