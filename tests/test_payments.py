import pytest
from fastapi.testclient import TestClient

from fringepay.domain import Money, PaymentStatus
from fringepay.main import app
from fringepay.providers import SandboxOutcome, SandboxProvider
from fringepay.service import CreatePayment, IdempotencyConflict, PaymentService

client = TestClient(app)

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

def test_create_payment_requires_idempotency_key() -> None:
    response = client.post(
        "/v1/payments",
        json={"amount_minor": 1000, "currency": "KES", "reference": "order-1"},
    )
    assert response.status_code == 422

def test_create_and_retrieve_sandbox_payment() -> None:
    response = client.post(
        "/v1/payments",
        headers={"Idempotency-Key": "api-key-1"},
        json={"amount_minor": 1000, "currency": "KES", "reference": "order-api-1"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["provider"] == "sandbox"
    assert body["status"] == "pending"
    fetched = client.get(f"/v1/payments/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == body["id"]
