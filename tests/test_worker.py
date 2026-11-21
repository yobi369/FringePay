from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fringepay.domain import Money, PaymentStatus
from fringepay.persistence import (
    Database,
    PaymentRepository,
    ProviderDispatchOutboxRow,
)
from fringepay.providers import (
    PaymentCommand,
    ProviderOutcomeUnknown,
    SandboxOutcome,
    SandboxProvider,
)
from fringepay.service import CreatePayment
from fringepay.worker import dispatch_one


@pytest.mark.asyncio
async def test_worker_dispatches_due_payment_and_completes_outbox(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'worker.db'}")
    await database.create_schema()
    repository = PaymentRepository(database)
    payment, _ = await repository.reserve(
        CreatePayment(Money(750, "KES"), "worker-order"), "worker-key"
    )

    handled = await dispatch_one(
        repository, SandboxProvider(SandboxOutcome.SUCCEEDED)
    )
    updated = await repository.get(payment.id)

    assert handled is True
    assert updated is not None
    assert updated.status is PaymentStatus.SUCCEEDED
    assert updated.provider_reference is not None
    assert await dispatch_one(repository, SandboxProvider()) is False
    await database.close()


@pytest.mark.asyncio
async def test_worker_recovers_expired_dispatch_lease(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'lease.db'}")
    await database.create_schema()
    repository = PaymentRepository(database)
    payment, _ = await repository.reserve(
        CreatePayment(Money(300, "KES"), "lease-order"), "lease-key"
    )
    claimed = await repository.claim_dispatch(payment.id)
    assert claimed is not None

    async with database.sessions() as session:
        async with session.begin():
            event = await session.get(ProviderDispatchOutboxRow, claimed[0])
            assert event is not None
            event.locked_at = datetime.now(UTC) - timedelta(minutes=2)

    handled = await dispatch_one(
        repository, SandboxProvider(SandboxOutcome.SUCCEEDED)
    )
    updated = await repository.get(payment.id)
    assert handled is True
    assert updated is not None
    assert updated.status is PaymentStatus.SUCCEEDED
    await database.close()


class UnknownOutcomeProvider:
    name = "daraja"

    async def initiate(self, command: PaymentCommand):
        raise ProviderOutcomeUnknown("simulated read timeout after submission")


@pytest.mark.asyncio
async def test_worker_quarantines_unknown_provider_outcome_without_retry(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'unknown.db'}")
    await database.create_schema()
    repository = PaymentRepository(database)
    payment, _ = await repository.reserve(
        CreatePayment(Money(1500, "KES"), "unknown-outcome-order"),
        "unknown-outcome-key",
        provider="daraja",
    )

    handled = await dispatch_one(repository, UnknownOutcomeProvider())
    updated = await repository.get(payment.id)

    assert handled is True
    assert updated is not None
    assert updated.status is PaymentStatus.PROCESSING
    assert await dispatch_one(repository, SandboxProvider()) is False
    await database.close()


@pytest.mark.asyncio
async def test_expired_daraja_dispatch_lease_is_quarantined_not_retried(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'daraja-lease.db'}")
    await database.create_schema()
    repository = PaymentRepository(database)
    payment, _ = await repository.reserve(
        CreatePayment(
            Money(5000, "KES"),
            "daraja-expired-order",
            phone_number="254712345678",
        ),
        "daraja-expired-key",
        provider="daraja",
    )
    claimed = await repository.claim_dispatch(payment.id)
    assert claimed is not None

    async with database.sessions() as session:
        async with session.begin():
            event = await session.get(ProviderDispatchOutboxRow, claimed[0])
            assert event is not None
            event.locked_at = datetime.now(UTC) - timedelta(minutes=2)

    handled = await dispatch_one(repository, SandboxProvider())
    updated = await repository.get(payment.id)

    assert handled is False
    assert updated is not None
    assert updated.status is PaymentStatus.PROCESSING
    assert await repository.claim_dispatch(payment.id) is None
    await database.close()
