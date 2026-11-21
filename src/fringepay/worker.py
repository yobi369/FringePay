"""Background worker for durable provider dispatch events."""

from __future__ import annotations

import asyncio
import logging

from fringepay.config import get_settings
from fringepay.domain import PaymentStatus
from fringepay.persistence import Database, PaymentRepository
from fringepay.provider_factory import build_provider
from fringepay.providers import (
    PaymentCommand,
    PaymentProvider,
    ProviderOutcomeUnknown,
    ProviderRejected,
    ProviderTemporaryError,
)

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
        phone_number=payment.phone_number,
    )
    try:
        result = await provider.initiate(command)
    except ProviderRejected:
        await repository.complete_dispatch(outbox_id, PaymentStatus.FAILED, None)
        logger.warning("Provider definitively rejected payment initiation")
        return True
    except ProviderTemporaryError:
        await repository.retry_dispatch(outbox_id, "provider_temporarily_unavailable")
        logger.warning("Provider unavailable before payment submission; retry scheduled")
        return True
    except ProviderOutcomeUnknown:
        await repository.mark_dispatch_unknown(outbox_id, "provider_outcome_unknown")
        logger.error("Provider outcome unknown; automatic retry disabled")
        return True
    except Exception:
        await repository.mark_dispatch_unknown(outbox_id, "provider_unclassified_error")
        logger.exception("Unclassified provider error; automatic retry disabled")
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
    provider = build_provider(settings)
    try:
        while True:
            did_work = await dispatch_one(repository, provider)
            if not did_work:
                await asyncio.sleep(poll_interval_seconds)
    finally:
        close_provider = getattr(provider, "aclose", None)
        if close_provider is not None:
            await close_provider()
        await database.close()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
