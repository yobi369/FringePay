from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from fringepay.config import get_settings
from fringepay.domain import Money, PaymentStatus
from fringepay.persistence import (
    Database,
    PaymentRepository,
    PaymentRow,
    PersistentIdempotencyConflict,
    ProviderDispatchOutboxRow,
)
from fringepay.service import CreatePayment


@pytest.mark.asyncio
async def test_payment_and_idempotency_survive_database_reopen(tmp_path: Path) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'fringepay.db'}"
    database = Database(url)
    await database.create_schema()
    repository = PaymentRepository(database)
    request = CreatePayment(Money(1250, "KES"), "order-persist-1")

    first, created = await repository.reserve(request, "persistent-key-1")
    assert created is True
    assert first.status is PaymentStatus.PENDING

    updated = await repository.apply_provider_result(
        first.id, PaymentStatus.PROCESSING, "sandbox-ref-1"
    )
    assert updated.status is PaymentStatus.PROCESSING
    await database.close()

    reopened = Database(url)
    repository_after_restart = PaymentRepository(reopened)
    replay, created_again = await repository_after_restart.reserve(
        request, "persistent-key-1"
    )
    assert created_again is False
    assert replay.id == first.id
    assert replay.status is PaymentStatus.PROCESSING
    assert replay.provider_reference == "sandbox-ref-1"
    await reopened.close()


@pytest.mark.asyncio
async def test_persistent_idempotency_rejects_changed_payload(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'conflict.db'}")
    await database.create_schema()
    repository = PaymentRepository(database)
    await repository.reserve(
        CreatePayment(Money(100, "KES"), "order-1"), "same-key"
    )

    with pytest.raises(PersistentIdempotencyConflict):
        await repository.reserve(
            CreatePayment(Money(200, "KES"), "order-1"), "same-key"
        )
    await database.close()


@pytest.mark.asyncio
async def test_repository_returns_none_for_unknown_payment(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'missing.db'}")
    await database.create_schema()
    repository = PaymentRepository(database)

    assert await repository.get("missing-payment") is None
    await database.close()


@pytest.mark.asyncio
async def test_outbox_claim_is_exclusive_and_completion_is_atomic(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'outbox.db'}")
    await database.create_schema()
    repository = PaymentRepository(database)
    request = CreatePayment(Money(900, "KES"), "outbox-order")
    payment, created = await repository.reserve(request, "outbox-key")
    assert created is True

    claim = await repository.claim_dispatch(payment.id)
    assert claim is not None
    outbox_id, claimed_payment = claim
    assert claimed_payment.id == payment.id
    assert await repository.claim_dispatch(payment.id) is None

    completed = await repository.complete_dispatch(
        outbox_id, PaymentStatus.SUCCEEDED, "sandbox-outbox-ref"
    )
    assert completed.status is PaymentStatus.SUCCEEDED
    assert completed.provider_reference == "sandbox-outbox-ref"
    assert await repository.claim_dispatch(payment.id) is None
    await database.close()


@pytest.mark.asyncio
async def test_outbox_failed_dispatch_can_be_retried(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'retry.db'}")
    await database.create_schema()
    repository = PaymentRepository(database)
    payment, _ = await repository.reserve(
        CreatePayment(Money(500, "KES"), "retry-order"), "retry-key"
    )

    first_claim = await repository.claim_dispatch(payment.id)
    assert first_claim is not None
    first_outbox_id, _ = first_claim
    await repository.retry_dispatch(first_outbox_id, "sandbox_unavailable", 0)

    second_claim = await repository.claim_dispatch(payment.id)
    assert second_claim is not None
    second_outbox_id, _ = second_claim
    assert second_outbox_id == first_outbox_id
    await repository.complete_dispatch(
        second_outbox_id, PaymentStatus.PENDING, "sandbox-retry-ref"
    )
    await database.close()


@pytest.mark.asyncio
async def test_tenant_credentials_isolate_payment_reads(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'tenants.db'}")
    await database.create_schema()
    repository = PaymentRepository(database)
    tenant_id, tenant_key = await repository.create_tenant("Merchant Alpha")
    assert await repository.authenticate_api_key("local-development-key") == "local"
    assert tenant_key.startswith("fp_test_")
    assert await repository.authenticate_api_key(tenant_key) == tenant_id
    assert await repository.revoke_api_key(tenant_id, tenant_key[:24]) is True
    assert await repository.authenticate_api_key(tenant_key) is None

    request = CreatePayment(Money(2300, "KES"), "tenant-isolation-order")
    payment, created = await repository.reserve(
        request,
        "tenant-isolation-key",
        tenant_id=tenant_id,
    )
    assert created is True
    assert await repository.get(payment.id, tenant_id) is not None
    assert await repository.get(payment.id, "local") is None

    local_payment, local_created = await repository.reserve(
        request,
        "tenant-isolation-key",
        tenant_id="local",
    )
    assert local_created is True
    assert local_payment.id != payment.id
    assert await repository.get(local_payment.id, "local") is not None
    await database.close()


@pytest.mark.asyncio
async def test_outbox_dead_letters_after_maximum_attempts(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'dead-letter.db'}")
    await database.create_schema()
    repository = PaymentRepository(database)
    payment, _ = await repository.reserve(
        CreatePayment(Money(100, "KES"), "dead-letter-order"),
        "dead-letter-key",
    )
    claim = await repository.claim_dispatch(payment.id)
    assert claim is not None
    outbox_id, _ = claim

    async with database.sessions() as session:
        async with session.begin():
            event = await session.get(ProviderDispatchOutboxRow, outbox_id)
            assert event is not None
            event.attempts = 12

    await repository.retry_dispatch(outbox_id, "provider_dispatch_failed")
    status = await repository.outbox_status(outbox_id)
    assert status == ("dead_letter", 12, "provider_dispatch_failed")
    await database.close()


@pytest.mark.asyncio
async def test_payment_phone_number_is_persisted_and_bound_to_idempotency(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'phone.db'}")
    await database.create_schema()
    repository = PaymentRepository(database)
    request = CreatePayment(
        Money(2500, "KES"),
        "phone-payment-order",
        phone_number="254712345678",
    )

    payment, created = await repository.reserve(
        request, "phone-payment-key", provider="daraja"
    )
    assert created is True
    assert payment.phone_number == "254712345678"

    fetched = await repository.get(payment.id)
    assert fetched is not None
    assert fetched.phone_number == "254712345678"

    with pytest.raises(PersistentIdempotencyConflict):
        await repository.reserve(
            CreatePayment(
                Money(2500, "KES"),
                "phone-payment-order",
                phone_number="254712345679",
            ),
            "phone-payment-key",
            provider="daraja",
        )
    await database.close()


@pytest.mark.asyncio
async def test_phone_number_is_encrypted_at_rest_when_key_is_configured(
    tmp_path: Path, monkeypatch
) -> None:
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("FRINGEPAY_PII_ENCRYPTION_KEY", key)
    get_settings.cache_clear()
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'encrypted-phone.db'}")
    await database.create_schema()
    repository = PaymentRepository(database)
    payment, _ = await repository.reserve(
        CreatePayment(
            Money(1000, "KES"),
            "encrypted-phone-order",
            phone_number="254712345678",
        ),
        "encrypted-phone-key",
        provider="daraja",
    )

    async with database.sessions() as session:
        stored = await session.get(PaymentRow, payment.id)
        assert stored is not None
        assert stored.phone_number is not None
        assert stored.phone_number.startswith("enc:v1:")
        assert "254712345678" not in stored.phone_number

    decrypted = await repository.get(payment.id)
    assert decrypted is not None
    assert decrypted.phone_number == "254712345678"
    await database.close()
    get_settings.cache_clear()


def test_production_repository_requires_pii_encryption_key(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("FRINGEPAY_ENVIRONMENT", "production")
    monkeypatch.delenv("FRINGEPAY_PII_ENCRYPTION_KEY", raising=False)
    get_settings.cache_clear()
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'production-pii.db'}")
    try:
        with pytest.raises(ValueError, match="required in production"):
            PaymentRepository(database)
    finally:
        get_settings.cache_clear()
