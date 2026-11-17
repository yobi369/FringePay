"""Provider webhook signature verification helpers."""

from __future__ import annotations

import hashlib
import hmac
import time


class InvalidWebhookSignature(ValueError):
    """Raised when a provider webhook signature is malformed or invalid."""


class StaleWebhookSignature(InvalidWebhookSignature):
    """Raised when a correctly formatted signature is outside the time window."""


def verify_hmac_webhook(
    secret: str,
    signature_header: str,
    body: bytes,
    *,
    tolerance_seconds: int = 300,
    now: int | None = None,
) -> None:
    """Verify timestamped HMAC-SHA256 signatures over timestamp plus body."""
    if not secret:
        raise InvalidWebhookSignature("webhook secret is not configured")
    fields: dict[str, str] = {}
    for item in signature_header.split(","):
        key, separator, value = item.strip().partition("=")
        if not separator or not key or not value:
            raise InvalidWebhookSignature("malformed webhook signature")
        fields[key] = value

    try:
        timestamp = int(fields["t"])
        supplied_signature = fields["v1"]
    except (KeyError, ValueError) as exc:
        raise InvalidWebhookSignature("malformed webhook signature") from exc

    current_time = int(time.time()) if now is None else now
    if abs(current_time - timestamp) > tolerance_seconds:
        raise StaleWebhookSignature("webhook signature timestamp is outside tolerance")

    signed_payload = str(timestamp).encode("ascii") + b"." + body
    expected_signature = hmac.new(
        secret.encode("utf-8"),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(supplied_signature, expected_signature):
        raise InvalidWebhookSignature("webhook signature does not match")
