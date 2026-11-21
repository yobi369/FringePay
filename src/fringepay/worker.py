"""Background worker for durable provider dispatch events."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time

from fringepay.config import get_settings
from fringepay.domain import PaymentStatus
from fringepay.persistence import (
    LATEST_SCHEMA_REVISION,
    Database,
    PaymentRepository,
    WebhookReplayConflict,
)
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


async def reconcile_daraja_statuses(
    repository: PaymentRepository,
    provider: PaymentProvider,
    limit: int = 100,
) -> int:
    """Poll unresolved Daraja checkouts so callbacks are not the only completion path."""
    query_status = getattr(provider, "query_stk_status", None)
    if query_status is None:
        return 0
    payments = await repository.list_pending_provider_payments("daraja", limit=limit)
    reconciled = 0
    for payment in payments:
        if payment.provider_reference is None:
            continue
        try:
            verified_status = await query_status(payment.provider_reference)
        except ProviderTemporaryError:
            logger.warning("Daraja status query unavailable; payment remains pending")
            continue
        if verified_status is None:
            continue
        fingerprint = (
            f"{payment.provider_reference}:{verified_status.value}".encode()
        )
        payload_hash = hashlib.sha256(fingerprint).hexdigest()
        try:
            await repository.apply_provider_webhook(
                "daraja",
                payment.provider_reference,
                payload_hash,
                payment.id,
                verified_status,
            )
        except WebhookReplayConflict:
            logger.error("Conflicting verified Daraja status event; manual review required")
            continue
        except ValueError:
            logger.warning("Daraja status transition rejected; manual review required")
            continue
        reconciled += 1
    return reconciled


async def run_worker(poll_interval_seconds: float = 1.0) -> None:
    settings = get_settings()
    database = Database(settings.database_url)
    provider = None
    try:
        if settings.environment != "production":
            await database.create_schema()
        else:
            await database.verify_schema_revision(LATEST_SCHEMA_REVISION)
        repository = PaymentRepository(database)
        provider = build_provider(settings)
        last_reconcile = 0.0
        while True:
            did_work = await dispatch_one(repository, provider)
            now = time.monotonic()
            if provider.name == "daraja" and now - last_reconcile >= 30:
                await reconcile_daraja_statuses(repository, provider)
                last_reconcile = now
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
