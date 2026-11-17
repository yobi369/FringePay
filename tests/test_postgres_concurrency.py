import asyncio
import os
from uuid import uuid4

import pytest

from fringepay.domain import Money
from fringepay.persistence import Database, PaymentRepository
from fringepay.service import CreatePayment


@pytest.mark.asyncio
async def test_postgres_concurrent_idempotency_and_outbox_claims() -> None:
    database_url = os.getenv("FRINGEPAY_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("PostgreSQL concurrency URL is not configured")

    database = Database(database_url)
    await database.create_schema()
    repository = PaymentRepository(database)
    request = CreatePayment(Money(4200, "KES"), f"concurrent-{uuid4()}")
    key = f"concurrent-key-{uuid4()}"

    reservations = await asyncio.gather(
        repository.reserve(request, key),
        repository.reserve(request, key),
    )
    payment_ids = {payment.id for payment, _ in reservations}
    created_count = sum(created for _, created in reservations)
    assert len(payment_ids) == 1
    assert created_count == 1

    payment_id = next(iter(payment_ids))
    claims = await asyncio.gather(
        repository.claim_dispatch(payment_id),
        repository.claim_dispatch(payment_id),
    )
    assert sum(claim is not None for claim in claims) == 1
    await database.close()
