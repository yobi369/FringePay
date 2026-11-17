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
