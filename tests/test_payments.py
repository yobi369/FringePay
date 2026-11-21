import pytest
from fastapi.testclient import TestClient

from fringepay.config import get_settings
from fringepay.domain import Money, PaymentStatus
from fringepay.main import app
from fringepay.providers import SandboxOutcome, SandboxProvider
from fringepay.service import CreatePayment, IdempotencyConflict, PaymentService


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    database_path = tmp_path / "api.db"
    monkeypatch.setenv("FRINGEPAY_DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
    get_settings.cache_clear()
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_service_returns_same_payment_for_same_idempotent_request() -> None:
    service = PaymentService(SandboxProvider())
    request = CreatePayment(Money(2500, "KES"), "order-42")
    first = await service.create(request, "key-1")
    second = await service.create(request, "key-1")
    assert first.id == second.id
    assert first.status is PaymentStatus.PENDING


@pytest.mark.asyncio
async def test_service_rejects_idempotency_key_reuse_with_different_payload() -> None:
    service = PaymentService(SandboxProvider())
    await service.create(CreatePayment(Money(2500, "KES"), "order-42"), "key-1")
    with pytest.raises(IdempotencyConflict):
        await service.create(CreatePayment(Money(3500, "KES"), "order-42"), "key-1")


@pytest.mark.asyncio
async def test_sandbox_can_simulate_success_without_real_money() -> None:
    service = PaymentService(SandboxProvider(SandboxOutcome.SUCCEEDED))
    payment = await service.create(CreatePayment(Money(100, "KES"), "test"), "key")
    assert payment.status is PaymentStatus.SUCCEEDED
    assert payment.provider == "sandbox"


@pytest.mark.asyncio
async def test_service_applies_only_valid_provider_status_transitions() -> None:
    service = PaymentService(SandboxProvider())
    payment = await service.create(
        CreatePayment(Money(100, "KES"), "lifecycle-test"), "lifecycle-key"
    )
    processing = service.apply_provider_status(payment.id, PaymentStatus.PROCESSING)
    assert processing.status is PaymentStatus.PROCESSING
    succeeded = service.apply_provider_status(payment.id, PaymentStatus.SUCCEEDED)
    assert succeeded.status is PaymentStatus.SUCCEEDED
    with pytest.raises(ValueError, match="cannot transition"):
        service.apply_provider_status(payment.id, PaymentStatus.PENDING)


@pytest.mark.asyncio
async def test_service_rejects_status_update_for_unknown_payment() -> None:
    service = PaymentService(SandboxProvider())
    with pytest.raises(KeyError, match="payment not found"):
        service.apply_provider_status("missing", PaymentStatus.SUCCEEDED)


def test_create_payment_requires_idempotency_key(api_client: TestClient) -> None:
    response = api_client.post(
        "/v1/payments",
        headers={"X-API-Key": "local-development-key"},
        json={"amount_minor": 1000, "currency": "KES", "reference": "order-1"},
    )
    assert response.status_code == 422


def test_create_and_retrieve_sandbox_payment(api_client: TestClient) -> None:
    response = api_client.post(
        "/v1/payments",
        headers={
            "Idempotency-Key": "api-key-1",
            "X-API-Key": "local-development-key",
        },
        json={"amount_minor": 1000, "currency": "KES", "reference": "order-api-1"},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["provider"] == "sandbox"
    assert body["status"] == "pending"
    fetched = api_client.get(
        f"/v1/payments/{body['id']}",
        headers={"X-API-Key": "local-development-key"},
    )
    assert fetched.status_code == 200
    assert fetched.json()["id"] == body["id"]


def test_api_idempotency_is_durable_and_payload_bound(api_client: TestClient) -> None:
    payload = {
        "amount_minor": 1500,
        "currency": "KES",
        "reference": "api-idempotency-order",
    }
    headers = {
        "Idempotency-Key": "api-idempotency-key",
        "X-API-Key": "local-development-key",
    }
    first = api_client.post("/v1/payments", headers=headers, json=payload)
    replay = api_client.post("/v1/payments", headers=headers, json=payload)
    conflict = api_client.post(
        "/v1/payments",
        headers=headers,
        json={**payload, "amount_minor": 1600},
    )

    assert first.status_code == 202
    assert replay.status_code == 202
    assert replay.json()["id"] == first.json()["id"]
    assert conflict.status_code == 409


def test_api_rejects_float_minor_units(api_client: TestClient) -> None:
    response = api_client.post(
        "/v1/payments",
        headers={
            "Idempotency-Key": "float-amount-key",
            "X-API-Key": "local-development-key",
        },
        json={"amount_minor": 10.5, "currency": "KES", "reference": "float-order"},
    )
    assert response.status_code == 422


def test_payment_api_rejects_missing_api_key(api_client: TestClient) -> None:
    response = api_client.post(
        "/v1/payments",
        headers={"Idempotency-Key": "unauthenticated-key"},
        json={"amount_minor": 100, "currency": "KES", "reference": "unauthenticated"},
    )
    assert response.status_code == 401


def test_daraja_payment_requires_a_valid_kenyan_phone_number(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "daraja-api.db"
    monkeypatch.setenv("FRINGEPAY_DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
    monkeypatch.setenv("FRINGEPAY_DEFAULT_PROVIDER", "daraja")
    monkeypatch.setenv("FRINGEPAY_DARAJA_CONSUMER_KEY", "sandbox-key")
    monkeypatch.setenv("FRINGEPAY_DARAJA_CONSUMER_SECRET", "sandbox-secret")
    monkeypatch.setenv("FRINGEPAY_DARAJA_SHORTCODE", "174379")
    monkeypatch.setenv("FRINGEPAY_DARAJA_PASSKEY", "sandbox-passkey")
    monkeypatch.setenv(
        "FRINGEPAY_DARAJA_CALLBACK_URL",
        "https://payments.example.test/v1/webhooks/daraja",
    )
    get_settings.cache_clear()
    try:
        with TestClient(app) as test_client:
            headers = {
                "X-API-Key": "local-development-key",
                "Idempotency-Key": "daraja-phone-key",
            }
            payload = {
                "amount_minor": 2500,
                "currency": "KES",
                "reference": "daraja-api-order",
            }
            missing = test_client.post("/v1/payments", headers=headers, json=payload)
            invalid = test_client.post(
                "/v1/payments",
                headers={**headers, "Idempotency-Key": "daraja-invalid-phone"},
                json={**payload, "phone_number": "0712345678"},
            )
            valid = test_client.post(
                "/v1/payments",
                headers={**headers, "Idempotency-Key": "daraja-valid-phone"},
                json={**payload, "phone_number": "254712345678"},
            )

        assert missing.status_code == 422
        assert invalid.status_code == 422
        assert valid.status_code == 202
        assert valid.json()["provider"] == "daraja"
        assert valid.json()["status"] == "pending"
    finally:
        get_settings.cache_clear()
