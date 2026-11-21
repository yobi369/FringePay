import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

from fringepay.config import get_settings
from fringepay.main import app
from fringepay.webhooks import (
    InvalidWebhookSignature,
    StaleWebhookSignature,
    verify_hmac_webhook,
)

SECRET = "test-webhook-secret"


def signed_header(body: bytes, timestamp: int | None = None) -> str:
    issued_at = int(time.time()) if timestamp is None else timestamp
    signed = str(issued_at).encode("ascii") + b"." + body
    digest = hmac.new(SECRET.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={issued_at},v1={digest}"


@pytest.fixture
def webhook_client(tmp_path, monkeypatch):
    database_path = tmp_path / "webhooks.db"
    monkeypatch.setenv("FRINGEPAY_DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
    monkeypatch.setenv("FRINGEPAY_SANDBOX_WEBHOOK_SECRET", SECRET)
    get_settings.cache_clear()
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


def test_hmac_verifier_rejects_stale_timestamp() -> None:
    body = b'{"event":"payment.updated"}'
    signature = signed_header(body, timestamp=1000)
    with pytest.raises(StaleWebhookSignature):
        verify_hmac_webhook(SECRET, signature, body, now=2000)


def test_hmac_verifier_rejects_invalid_signature() -> None:
    with pytest.raises(InvalidWebhookSignature):
        verify_hmac_webhook(SECRET, "t=1,v1=invalid", b"payload", now=1)


def test_signed_webhook_updates_payment_and_rejects_replays(
    webhook_client: TestClient,
) -> None:
    created = webhook_client.post(
        "/v1/payments",
        headers={
            "X-API-Key": "local-development-key",
            "Idempotency-Key": "webhook-payment-key",
        },
        json={
            "amount_minor": 800,
            "currency": "KES",
            "reference": "webhook-payment",
        },
    )
    assert created.status_code == 202
    payment_id = created.json()["id"]

    payload = {"payment_id": payment_id, "status": "processing"}
    raw_body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = {
        "X-Provider-Event-Id": "sandbox-event-001",
        "X-FringePay-Signature": signed_header(raw_body),
    }
    first = webhook_client.post(
        "/v1/webhooks/sandbox",
        content=raw_body,
        headers=headers,
    )
    replay = webhook_client.post(
        "/v1/webhooks/sandbox",
        content=raw_body,
        headers=headers,
    )

    assert first.status_code == 200
    assert first.json()["status"] == "processing"
    assert first.json()["duplicate"] is False
    assert replay.status_code == 200
    assert replay.json()["duplicate"] is True

    changed_body = json.dumps(
        {"payment_id": payment_id, "status": "succeeded"},
        separators=(",", ":"),
    ).encode("utf-8")
    conflict = webhook_client.post(
        "/v1/webhooks/sandbox",
        content=changed_body,
        headers={
            "X-Provider-Event-Id": "sandbox-event-001",
            "X-FringePay-Signature": signed_header(changed_body),
        },
    )
    assert conflict.status_code == 409


def test_signed_webhook_rejects_invalid_signature(
    webhook_client: TestClient,
) -> None:
    response = webhook_client.post(
        "/v1/webhooks/sandbox",
        content=b'{"payment_id":"missing","status":"succeeded"}',
        headers={
            "X-Provider-Event-Id": "bad-signature-event",
            "X-FringePay-Signature": "t=1,v1=bad",
        },
    )
    assert response.status_code == 401
