from datetime import UTC, datetime
from pathlib import Path

import pytest

from fringepay.domain import Money, PaymentStatus
from fringepay.persistence import Database, PaymentRepository
from fringepay.reconciliation import (
    SettlementConflict,
    SettlementLine,
    SettlementStatus,
)
from fringepay.service import CreatePayment


@pytest.mark.asyncio
async def test_settlement_reconciliation_matches_and_is_idempotent(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'settlement.db'}")
    await database.create_schema()
    repository = PaymentRepository(database)
    payment, _ = await repository.reserve(
        CreatePayment(Money(2500, "KES"), "settled-order"),
        "settled-order-key",
    )
    await repository.apply_provider_result(
        payment.id, PaymentStatus.SUCCEEDED, "provider-ref-2500"
    )
    line = SettlementLine(
        provider_reference="provider-ref-2500",
        amount_minor=2500,
        currency="KES",
        settled_at=datetime.now(UTC),
        source_reference="statement-2026-11-17",
    )

    record_id, status, matched_payment, created = (
        await repository.reconcile_settlement("local", "sandbox", line)
    )
    replay_id, replay_status, replay_payment, replay_created = (
        await repository.reconcile_settlement("local", "sandbox", line)
    )

    assert created is True
    assert status is SettlementStatus.MATCHED
    assert matched_payment == payment.id
    assert replay_created is False
    assert replay_id == record_id
    assert replay_status is SettlementStatus.MATCHED
    assert replay_payment == payment.id

    changed_line = SettlementLine(
        provider_reference="provider-ref-2500",
        amount_minor=2600,
        currency="KES",
        settled_at=line.settled_at,
        source_reference=line.source_reference,
    )
    with pytest.raises(SettlementConflict):
        await repository.reconcile_settlement("local", "sandbox", changed_line)
    await database.close()


@pytest.mark.asyncio
async def test_settlement_reconciliation_distinguishes_unmatched_pending_and_mismatch(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'settlement-states.db'}")
    await database.create_schema()
    repository = PaymentRepository(database)

    pending, _ = await repository.reserve(
        CreatePayment(Money(1000, "KES"), "pending-settlement"),
        "pending-settlement-key",
    )
    await repository.apply_provider_result(
        pending.id, PaymentStatus.PROCESSING, "provider-pending"
    )
    pending_line = SettlementLine(
        "provider-pending",
        1000,
        "KES",
        datetime.now(UTC),
        "statement-pending",
    )
    _, pending_status, _, _ = await repository.reconcile_settlement(
        "local", "sandbox", pending_line
    )

    mismatch, _ = await repository.reserve(
        CreatePayment(Money(2000, "KES"), "mismatch-settlement"),
        "mismatch-settlement-key",
    )
    await repository.apply_provider_result(
        mismatch.id, PaymentStatus.SUCCEEDED, "provider-mismatch"
    )
    mismatch_line = SettlementLine(
        "provider-mismatch",
        1999,
        "KES",
        datetime.now(UTC),
        "statement-mismatch",
    )
    _, mismatch_status, mismatch_payment, _ = await repository.reconcile_settlement(
        "local", "sandbox", mismatch_line
    )

    unmatched_line = SettlementLine(
        "unknown-provider-reference",
        500,
        "KES",
        datetime.now(UTC),
        "statement-unmatched",
    )
    _, unmatched_status, unmatched_payment, _ = await repository.reconcile_settlement(
        "local", "sandbox", unmatched_line
    )

    assert pending_status is SettlementStatus.PENDING
    assert mismatch_status is SettlementStatus.MISMATCH
    assert mismatch_payment == mismatch.id
    assert unmatched_status is SettlementStatus.UNMATCHED
    assert unmatched_payment is None
    await database.close()
