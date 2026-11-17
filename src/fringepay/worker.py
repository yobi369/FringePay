"""Background worker for durable provider dispatch events."""

from __future__ import annotations

import asyncio
import logging

from fringepay.config import get_settings
from fringepay.persistence import Database, PaymentRepository
from fringepay.providers import PaymentCommand, PaymentProvider, SandboxProvider

logger = logging.getLogger(__name__)


async def dispatch_one(
    repository: PaymentRepository, provider: PaymentProvider
) -> bool:
    """Dispatch one due event; return whether an event was handled."""
    await repository.recover_stale_dispatches()
    claimed = await repository.claim_next_dispatch()
    if claimed is None:
        return False

    outbox_id, payment = claimed
    command = PaymentCommand(
        payment_id=payment.id,
        amount=payment.amount,
        reference=payment.reference,
    )
    try:
        result = await provider.initiate(command)
    except Exception:
        await repository.retry_dispatch(outbox_id, "provider_dispatch_failed")
        logger.error("Provider dispatch failed; event scheduled for retry")
        return True

    await repository.complete_dispatch(
        outbox_id,
        result.status,
        result.provider_reference,
    )
    return True


async def run_worker(poll_interval_seconds: float = 1.0) -> None:
    settings = get_settings()
    database = Database(settings.database_url)
    if settings.environment != "production":
        await database.create_schema()
    repository = PaymentRepository(database)
    provider = SandboxProvider()
    try:
        while True:
            did_work = await dispatch_one(repository, provider)
            if not did_work:
                await asyncio.sleep(poll_interval_seconds)
    finally:
        await database.close()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
