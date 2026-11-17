from pathlib import Path

import pytest

from fringepay.domain import Money, PaymentStatus
from fringepay.persistence import (
    Database,
    PaymentRepository,
    PersistentIdempotencyConflict,
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
