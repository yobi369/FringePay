"""Async SQLAlchemy persistence and transactional idempotency primitives."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
    func,
    select,
    text,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from fringepay.config import get_settings
from fringepay.domain import Money, Payment, PaymentStatus
from fringepay.ledger import EntrySide, Journal
from fringepay.pii import PhoneNumberCipher
from fringepay.reconciliation import (
    SettlementConflict,
    SettlementLine,
    SettlementStatus,
)
from fringepay.service import CreatePayment

LATEST_SCHEMA_REVISION = "0007_payment_phone_number"


class Base(DeclarativeBase):
    """Base metadata for FringePay persistence models."""


class TenantRow(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class ApiCredentialRow(Base):
    __tablename__ = "api_credentials"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False
    )
    key_prefix: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PaymentRow(Base):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "provider", "provider_reference",
            name="uq_payment_tenant_provider_reference",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_payments_tenant_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False
    )
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    reference: Mapped[str] = mapped_column(String(128), nullable=False)
    phone_number: Mapped[str | None] = mapped_column(String(512))
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_reference: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )


class IdempotencyRow(Base):
    __tablename__ = "idempotency_keys"

    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="RESTRICT"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("payments.id", ondelete="RESTRICT"), unique=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )



class ProviderDispatchOutboxRow(Base):
    __tablename__ = "provider_dispatch_outbox"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    payment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("payments.id", ondelete="RESTRICT"), unique=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )


class LedgerAccountRow(Base):
    __tablename__ = "ledger_accounts"
    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "code", name="pk_ledger_accounts"),
        ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="RESTRICT"
        ),
    )

    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    normal_side: Mapped[str] = mapped_column(String(6), nullable=False)


class LedgerTransactionRow(Base):
    __tablename__ = "ledger_transactions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "reference", name="uq_ledger_tenant_reference"),
        ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="RESTRICT"
        ),
        UniqueConstraint("tenant_id", "id", name="uq_ledger_tenant_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    reference: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    description: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class LedgerEntryRow(Base):
    __tablename__ = "ledger_entries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "transaction_id"],
            ["ledger_transactions.tenant_id", "ledger_transactions.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "account_code"],
            ["ledger_accounts.tenant_id", "ledger_accounts.code"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "transaction_id", "account_code"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    transaction_id: Mapped[str] = mapped_column(String(36), nullable=False)
    account_code: Mapped[str] = mapped_column(String(64), nullable=False)
    side: Mapped[str] = mapped_column(String(6), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class ProviderWebhookEventRow(Base):
    __tablename__ = "provider_webhook_events"
    __table_args__ = (
        UniqueConstraint("provider", "event_id", name="uq_provider_webhook_event"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("payments.id", ondelete="RESTRICT"), nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class WebhookReplayConflict(ValueError):
    """Raised when a provider reuses an event ID for different content."""


class SettlementRecordRow(Base):
    __tablename__ = "settlement_records"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "provider",
            "provider_reference",
            name="uq_settlement_provider_reference",
        ),
        ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "payment_id"],
            ["payments.tenant_id", "payments.id"],
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_reference: Mapped[str] = mapped_column(String(128), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    settled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_reference: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    payment_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class PersistentIdempotencyConflict(ValueError):
    """Raised when a durable idempotency key is reused with a different request."""


class Database:
    """Owns an async engine and session factory; callers control its lifecycle."""

    def __init__(self, url: str, *, echo: bool = False) -> None:
        self.engine: AsyncEngine = create_async_engine(url, echo=echo, pool_pre_ping=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def create_schema(self) -> None:
        """Create and seed local development schema; deployments use migrations."""
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with self.sessions() as session:
            async with session.begin():
                tenant = await session.get(TenantRow, "local")
                if tenant is None:
                    session.add(TenantRow(id="local", name="Local Development"))
                    await session.flush()
                local_key_hash = hashlib.sha256(
                    b"local-development-key"
                ).hexdigest()
                credential = await session.scalar(
                    select(ApiCredentialRow).where(
                        ApiCredentialRow.key_hash == local_key_hash
                    )
                )
                if credential is None:
                    session.add(
                        ApiCredentialRow(
                            id=str(uuid4()),
                            tenant_id="local",
                            key_prefix="local-development-key",
                            key_hash=local_key_hash,
                            label="Local development key",
                        )
                    )

    async def verify_schema_revision(self, expected_revision: str) -> None:
        """Fail startup when a deployed database has not reached the expected schema."""
        async with self.engine.connect() as connection:
            result = await connection.execute(
                text("SELECT version_num FROM alembic_version")
            )
            revisions = result.scalars().all()
        if revisions != [expected_revision]:
            raise RuntimeError(
                f"database schema revision mismatch: expected {expected_revision}"
            )

    async def close(self) -> None:
        await self.engine.dispose()


class PaymentRepository:
    """Durable payment storage with a database-enforced idempotency key."""

    def __init__(self, database: Database) -> None:
        self.database = database
        settings = get_settings()
        self.phone_cipher = PhoneNumberCipher(
            settings.pii_encryption_key,
            required=settings.environment == "production",
        )

    @staticmethod
    def _request_hash(request: CreatePayment) -> str:
        payload = {
            "amount_minor": request.amount.minor_units,
            "currency": request.amount.currency,
            "reference": request.reference,
            "phone_number": request.phone_number,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _to_domain(self, row: PaymentRow) -> Payment:
        return Payment(
            id=row.id,
            amount=Money(row.amount_minor, row.currency),
            reference=row.reference,
            provider=row.provider,
            provider_reference=row.provider_reference,
            status=PaymentStatus(row.status),
            phone_number=self.phone_cipher.decrypt(row.phone_number),
        )

    async def reserve(
        self,
        request: CreatePayment,
        idempotency_key: str,
        provider: str = "sandbox",
        tenant_id: str = "local",
    ) -> tuple[Payment, bool]:
        """Persist a payment reservation once; return (payment, newly_created).

        The unique key is enforced by the database, so concurrent workers cannot
        independently reserve two payments for the same idempotency key.
        """
        if not idempotency_key or len(idempotency_key) > 128:
            raise ValueError("idempotency key must contain 1 to 128 characters")
        request_hash = self._request_hash(request)
        try:
            async with self.database.sessions() as session:
                async with session.begin():
                    existing = await session.get(
                        IdempotencyRow, (tenant_id, idempotency_key)
                    )
                    if existing is not None:
                        if existing.request_hash != request_hash:
                            raise PersistentIdempotencyConflict(
                                "idempotency key was already used for another request"
                            )
                        row = await session.get(PaymentRow, existing.payment_id)
                        if row is None:
                            raise RuntimeError("idempotency record has no payment")
                        if row.tenant_id != tenant_id:
                            raise PersistentIdempotencyConflict(
                                "idempotency key is already in use"
                            )
                        return self._to_domain(row), False

                    payment_id = str(uuid4())
                    row = PaymentRow(
                        id=payment_id,
                        tenant_id=tenant_id,
                        amount_minor=request.amount.minor_units,
                        currency=request.amount.currency,
                        reference=request.reference,
                        phone_number=self.phone_cipher.encrypt(request.phone_number),
                        provider=provider,
                        provider_reference=None,
                        status=PaymentStatus.PENDING.value,
                    )
                    session.add(row)
                    await session.flush()
                    session.add(
                        IdempotencyRow(
                            tenant_id=tenant_id,
                            key=idempotency_key,
                            request_hash=request_hash,
                            payment_id=payment_id,
                        )
                    )
                    session.add(
                        ProviderDispatchOutboxRow(
                            id=str(uuid4()),
                            payment_id=payment_id,
                            status="pending",
                        )
                    )
                    await session.flush()
                    return self._to_domain(row), True
        except IntegrityError:
            # A competing transaction may have inserted the same key first.
            async with self.database.sessions() as session:
                existing = await session.get(
                    IdempotencyRow, (tenant_id, idempotency_key)
                )
                if existing is None:
                    raise
                if existing.request_hash != request_hash:
                    raise PersistentIdempotencyConflict(
                        "idempotency key was already used for another request"
                    ) from None
                row = await session.get(PaymentRow, existing.payment_id)
                if row is None:
                    raise RuntimeError("idempotency record has no payment") from None
                if row.tenant_id != tenant_id:
                    raise PersistentIdempotencyConflict(
                        "idempotency key is already in use"
                    ) from None
                return self._to_domain(row), False

    async def apply_provider_result(
        self,
        payment_id: str,
        status: PaymentStatus,
        provider_reference: str | None,
    ) -> Payment:
        async with self.database.sessions() as session:
            async with session.begin():
                row = await session.get(PaymentRow, payment_id)
                if row is None:
                    raise KeyError(f"payment not found: {payment_id}")
                current = self._to_domain(row)
                updated = current.transition_to(status)
                row.status = updated.status.value
                row.provider_reference = provider_reference
                row.updated_at = datetime.now(UTC)
                await session.flush()
                return replace(updated, provider_reference=provider_reference)



    async def claim_dispatch(
        self, payment_id: str
    ) -> tuple[str, Payment] | None:
        """Atomically claim a pending/retry dispatch for one payment."""
        now = datetime.now(UTC)
        async with self.database.sessions() as session:
            async with session.begin():
                statement = (
                    update(ProviderDispatchOutboxRow)
                    .where(
                        ProviderDispatchOutboxRow.payment_id == payment_id,
                        ProviderDispatchOutboxRow.status.in_(("pending", "retry")),
                        ProviderDispatchOutboxRow.available_at <= now,
                    )
                    .values(
                        status="processing",
                        attempts=ProviderDispatchOutboxRow.attempts + 1,
                        locked_at=now,
                        updated_at=now,
                    )
                    .returning(ProviderDispatchOutboxRow.id)
                )
                result = await session.execute(statement)
                outbox_id = result.scalar_one_or_none()
                if outbox_id is None:
                    return None
                payment_row = await session.get(PaymentRow, payment_id)
                if payment_row is None:
                    raise RuntimeError("outbox event has no payment")
                return outbox_id, self._to_domain(payment_row)

    async def complete_dispatch(
        self,
        outbox_id: str,
        status: PaymentStatus,
        provider_reference: str | None,
    ) -> Payment:
        """Commit provider result and outbox completion atomically."""
        async with self.database.sessions() as session:
            async with session.begin():
                event = await session.get(ProviderDispatchOutboxRow, outbox_id)
                if event is None or event.status != "processing":
                    raise ValueError("dispatch event is not claimed")
                payment_row = await session.get(PaymentRow, event.payment_id)
                if payment_row is None:
                    raise RuntimeError("outbox event has no payment")
                current = self._to_domain(payment_row)
                updated = current.transition_to(status)
                payment_row.status = updated.status.value
                payment_row.provider_reference = provider_reference
                payment_row.updated_at = datetime.now(UTC)
                event.status = "completed"
                event.locked_at = None
                event.last_error_code = None
                event.updated_at = datetime.now(UTC)
                await session.flush()
                return replace(updated, provider_reference=provider_reference)


    async def claim_next_dispatch(self) -> tuple[str, Payment] | None:
        """Atomically claim the oldest due outbox event for a worker."""
        now = datetime.now(UTC)
        async with self.database.sessions() as session:
            async with session.begin():
                next_event = (
                    select(ProviderDispatchOutboxRow.id)
                    .where(
                        ProviderDispatchOutboxRow.status.in_(("pending", "retry")),
                        ProviderDispatchOutboxRow.available_at <= now,
                    )
                    .order_by(ProviderDispatchOutboxRow.created_at)
                    .limit(1)
                    .scalar_subquery()
                )
                statement = (
                    update(ProviderDispatchOutboxRow)
                    .where(
                        ProviderDispatchOutboxRow.id == next_event,
                        ProviderDispatchOutboxRow.status.in_(("pending", "retry")),
                    )
                    .values(
                        status="processing",
                        attempts=ProviderDispatchOutboxRow.attempts + 1,
                        locked_at=now,
                        updated_at=now,
                    )
                    .returning(
                        ProviderDispatchOutboxRow.id,
                        ProviderDispatchOutboxRow.payment_id,
                    )
                )
                result = await session.execute(statement)
                claimed = result.one_or_none()
                if claimed is None:
                    return None
                payment_row = await session.get(PaymentRow, claimed.payment_id)
                if payment_row is None:
                    raise RuntimeError("outbox event has no payment")
                return claimed.id, self._to_domain(payment_row)

    async def recover_stale_dispatches(self, stale_after_seconds: int = 60) -> int:
        """Recover leases without blindly repeating a possibly accepted live charge."""
        now = datetime.now(UTC)
        cutoff = now - timedelta(seconds=stale_after_seconds)
        recovered = 0
        async with self.database.sessions() as session:
            async with session.begin():
                events = (
                    await session.scalars(
                        select(ProviderDispatchOutboxRow)
                        .where(
                            ProviderDispatchOutboxRow.status == "processing",
                            ProviderDispatchOutboxRow.locked_at < cutoff,
                        )
                        .with_for_update(skip_locked=True)
                    )
                ).all()
                for event in events:
                    payment = await session.get(PaymentRow, event.payment_id)
                    if payment is None:
                        raise RuntimeError("outbox event has no payment")
                    event.locked_at = None
                    event.updated_at = now
                    if payment.provider == "sandbox":
                        event.status = "retry"
                        event.available_at = now
                        event.last_error_code = "dispatch_lease_expired"
                    else:
                        # A worker may have crashed after the provider accepted the
                        # request but before the acknowledgement was persisted.
                        # Quarantine this payment for status query/manual resolution.
                        event.status = "unknown"
                        event.last_error_code = "dispatch_lease_expired_unknown"
                        if payment.status == PaymentStatus.PENDING.value:
                            payment.status = PaymentStatus.PROCESSING.value
                            payment.updated_at = now
                    recovered += 1
        return recovered

    async def retry_dispatch(
        self,
        outbox_id: str,
        error_code: str,
        retry_delay_seconds: int | None = None,
    ) -> None:
        """Apply bounded exponential backoff and dead-letter exhausted events."""
        async with self.database.sessions() as session:
            async with session.begin():
                event = await session.get(ProviderDispatchOutboxRow, outbox_id)
                if event is None or event.status != "processing":
                    raise ValueError("dispatch event is not claimed")
                now = datetime.now(UTC)
                if event.attempts >= 12:
                    event.status = "dead_letter"
                else:
                    delay = retry_delay_seconds
                    if delay is None:
                        delay = min(300, 2 ** min(event.attempts, 8))
                    event.status = "retry"
                    event.available_at = now + timedelta(seconds=delay)
                event.locked_at = None
                event.last_error_code = error_code[:64]
                event.updated_at = now

    async def mark_dispatch_unknown(self, outbox_id: str, error_code: str) -> None:
        """Stop automatic retries when a provider may already have accepted a charge."""
        async with self.database.sessions() as session:
            async with session.begin():
                event = await session.get(ProviderDispatchOutboxRow, outbox_id)
                if event is None or event.status != "processing":
                    raise ValueError("dispatch event is not claimed")
                payment = await session.get(PaymentRow, event.payment_id)
                if payment is None:
                    raise RuntimeError("outbox event has no payment")
                if payment.status == PaymentStatus.PENDING.value:
                    payment.status = PaymentStatus.PROCESSING.value
                    payment.updated_at = datetime.now(UTC)
                event.status = "unknown"
                event.locked_at = None
                event.last_error_code = error_code[:64]
                event.updated_at = datetime.now(UTC)

    async def outbox_status(self, outbox_id: str) -> tuple[str, int, str | None] | None:
        async with self.database.sessions() as session:
            event = await session.get(ProviderDispatchOutboxRow, outbox_id)
            if event is None:
                return None
            return event.status, event.attempts, event.last_error_code



    async def apply_provider_webhook(
        self,
        provider: str,
        event_id: str,
        payload_hash: str,
        payment_id: str,
        new_status: PaymentStatus,
    ) -> tuple[Payment, bool]:
        """Apply a verified webhook once, atomically with its replay record."""
        if not provider or len(provider) > 64:
            raise ValueError("provider name must contain 1 to 64 characters")
        if not event_id or len(event_id) > 128:
            raise ValueError("provider event ID must contain 1 to 128 characters")
        try:
            async with self.database.sessions() as session:
                async with session.begin():
                    existing = await session.scalar(
                        select(ProviderWebhookEventRow).where(
                            ProviderWebhookEventRow.provider == provider,
                            ProviderWebhookEventRow.event_id == event_id,
                        )
                    )
                    if existing is not None:
                        if existing.payload_hash != payload_hash:
                            raise WebhookReplayConflict(
                                "provider event ID was reused with a different payload"
                            )
                        payment_row = await session.get(PaymentRow, existing.payment_id)
                        if payment_row is None:
                            raise RuntimeError("webhook event has no payment")
                        return self._to_domain(payment_row), False

                    payment_row = await session.scalar(
                        select(PaymentRow)
                        .where(PaymentRow.id == payment_id)
                        .with_for_update()
                    )
                    if payment_row is None:
                        raise KeyError(f"payment not found: {payment_id}")
                    if payment_row.provider != provider:
                        raise ValueError("webhook provider does not match payment provider")
                    current = self._to_domain(payment_row)
                    updated = current.transition_to(new_status)
                    payment_row.status = updated.status.value
                    payment_row.updated_at = datetime.now(UTC)
                    session.add(
                        ProviderWebhookEventRow(
                            id=str(uuid4()),
                            provider=provider,
                            event_id=event_id,
                            payload_hash=payload_hash,
                            payment_id=payment_id,
                        )
                    )
                    await session.flush()
                    return updated, True
        except IntegrityError:
            async with self.database.sessions() as session:
                existing = await session.scalar(
                    select(ProviderWebhookEventRow).where(
                        ProviderWebhookEventRow.provider == provider,
                        ProviderWebhookEventRow.event_id == event_id,
                    )
                )
                if existing is None:
                    raise
                if existing.payload_hash != payload_hash:
                    raise WebhookReplayConflict(
                        "provider event ID was reused with a different payload"
                    ) from None
                payment_row = await session.get(PaymentRow, existing.payment_id)
                if payment_row is None:
                    raise RuntimeError("webhook event has no payment") from None
                return self._to_domain(payment_row), False


    async def reconcile_settlement(
        self,
        tenant_id: str,
        provider: str,
        line: SettlementLine,
    ) -> tuple[str, SettlementStatus, str | None, bool]:
        """Match one imported statement row without treating it as a payment command."""
        if not provider or len(provider) > 64:
            raise ValueError("provider name must contain 1 to 64 characters")
        payload_hash = line.fingerprint(provider)
        try:
            async with self.database.sessions() as session:
                async with session.begin():
                    existing = await session.scalar(
                        select(SettlementRecordRow).where(
                            SettlementRecordRow.tenant_id == tenant_id,
                            SettlementRecordRow.provider == provider,
                            SettlementRecordRow.provider_reference
                            == line.provider_reference,
                        )
                    )
                    if existing is not None:
                        if existing.payload_hash != payload_hash:
                            raise SettlementConflict(
                                "settlement reference was reused with different statement data"
                            )
                        return (
                            existing.id,
                            SettlementStatus(existing.status),
                            existing.payment_id,
                            False,
                        )

                    payment = await session.scalar(
                        select(PaymentRow).where(
                            PaymentRow.tenant_id == tenant_id,
                            PaymentRow.provider == provider,
                            PaymentRow.provider_reference == line.provider_reference,
                        )
                    )
                    if payment is None:
                        status = SettlementStatus.UNMATCHED
                        payment_id = None
                    elif (
                        payment.amount_minor != line.amount_minor
                        or payment.currency != line.currency
                    ):
                        status = SettlementStatus.MISMATCH
                        payment_id = payment.id
                    elif payment.status != PaymentStatus.SUCCEEDED.value:
                        status = SettlementStatus.PENDING
                        payment_id = payment.id
                    else:
                        status = SettlementStatus.MATCHED
                        payment_id = payment.id

                    record_id = str(uuid4())
                    session.add(
                        SettlementRecordRow(
                            id=record_id,
                            tenant_id=tenant_id,
                            provider=provider,
                            provider_reference=line.provider_reference,
                            amount_minor=line.amount_minor,
                            currency=line.currency,
                            settled_at=line.settled_at,
                            source_reference=line.source_reference,
                            payload_hash=payload_hash,
                            status=status.value,
                            payment_id=payment_id,
                        )
                    )
                    await session.flush()
                    return record_id, status, payment_id, True
        except IntegrityError:
            async with self.database.sessions() as session:
                existing = await session.scalar(
                    select(SettlementRecordRow).where(
                        SettlementRecordRow.tenant_id == tenant_id,
                        SettlementRecordRow.provider == provider,
                        SettlementRecordRow.provider_reference
                        == line.provider_reference,
                    )
                )
                if existing is None:
                    raise
                if existing.payload_hash != payload_hash:
                    raise SettlementConflict(
                        "settlement reference was reused with different statement data"
                    ) from None
                return (
                    existing.id,
                    SettlementStatus(existing.status),
                    existing.payment_id,
                    False,
                )

    async def create_ledger_account(
        self,
        code: str,
        name: str,
        currency: str,
        normal_side: EntrySide,
        tenant_id: str = "local",
    ) -> None:
        if not code or len(code) > 64 or not name or len(name) > 128:
            raise ValueError("ledger account code and name are required")
        if (
            not currency.isascii()
            or len(currency) != 3
            or not currency.isalpha()
            or not currency.isupper()
        ):
            raise ValueError("ledger account currency must be uppercase ISO code")
        async with self.database.sessions() as session:
            async with session.begin():
                existing = await session.get(LedgerAccountRow, (tenant_id, code))
                if existing is not None:
                    if (
                        existing.name != name
                        or existing.currency != currency
                        or existing.normal_side != normal_side.value
                    ):
                        raise ValueError("ledger account already exists with different details")
                    return
                session.add(
                    LedgerAccountRow(
                        tenant_id=tenant_id,
                        code=code,
                        name=name,
                        currency=currency,
                        normal_side=normal_side.value,
                    )
                )

    async def post_journal(
        self, journal: Journal, tenant_id: str = "local"
    ) -> tuple[str, bool]:
        """Post a balanced journal once, using its reference as an idempotency key."""
        request_hash = journal.fingerprint()
        try:
            async with self.database.sessions() as session:
                async with session.begin():
                    existing = await session.scalar(
                        select(LedgerTransactionRow).where(
                            LedgerTransactionRow.tenant_id == tenant_id,
                            LedgerTransactionRow.reference == journal.reference
                        )
                    )
                    if existing is not None:
                        if existing.request_hash != request_hash:
                            raise ValueError(
                                "journal reference was already used with different entries"
                            )
                        return existing.id, False

                    for line in journal.lines:
                        account = await session.get(
                            LedgerAccountRow, (tenant_id, line.account_code)
                        )
                        if account is None:
                            raise ValueError(
                                f"ledger account does not exist: {line.account_code}"
                            )
                        if account.currency != journal.currency:
                            raise ValueError(
                                f"ledger account currency mismatch: {line.account_code}"
                            )

                    transaction_id = str(uuid4())
                    session.add(
                        LedgerTransactionRow(
                            id=transaction_id,
                            tenant_id=tenant_id,
                            reference=journal.reference,
                            request_hash=request_hash,
                            currency=journal.currency,
                            description=journal.description,
                        )
                    )
                    await session.flush()
                    for line in journal.lines:
                        session.add(
                            LedgerEntryRow(
                                id=str(uuid4()),
                                tenant_id=tenant_id,
                                transaction_id=transaction_id,
                                account_code=line.account_code,
                                side=line.side.value,
                                amount_minor=line.amount_minor,
                            )
                        )
                    await session.flush()
                    return transaction_id, True
        except IntegrityError:
            async with self.database.sessions() as session:
                existing = await session.scalar(
                    select(LedgerTransactionRow).where(
                        LedgerTransactionRow.reference == journal.reference
                    )
                )
                if existing is None:
                    raise
                if existing.request_hash != request_hash:
                    raise ValueError(
                        "journal reference was already used with different entries"
                    ) from None
                return existing.id, False

    async def account_balance(
        self, account_code: str, tenant_id: str = "local"
    ) -> int:
        async with self.database.sessions() as session:
            account = await session.get(LedgerAccountRow, (tenant_id, account_code))
            if account is None:
                raise KeyError(f"ledger account not found: {account_code}")
            debit_total = await session.scalar(
                select(func.coalesce(func.sum(LedgerEntryRow.amount_minor), 0)).where(
                    LedgerEntryRow.tenant_id == tenant_id,
                    LedgerEntryRow.account_code == account_code,
                    LedgerEntryRow.side == EntrySide.DEBIT.value,
                )
            )
            credit_total = await session.scalar(
                select(func.coalesce(func.sum(LedgerEntryRow.amount_minor), 0)).where(
                    LedgerEntryRow.tenant_id == tenant_id,
                    LedgerEntryRow.account_code == account_code,
                    LedgerEntryRow.side == EntrySide.CREDIT.value,
                )
            )
            if account.normal_side == EntrySide.DEBIT.value:
                return int(debit_total) - int(credit_total)
            return int(credit_total) - int(debit_total)

    async def list_pending_provider_payments(
        self, provider: str, limit: int = 100
    ) -> list[Payment]:
        """List non-final payments with provider references for status reconciliation."""
        if limit < 1 or limit > 500:
            raise ValueError("reconciliation limit must be between 1 and 500")
        async with self.database.sessions() as session:
            rows = (
                await session.scalars(
                    select(PaymentRow)
                    .where(
                        PaymentRow.provider == provider,
                        PaymentRow.provider_reference.is_not(None),
                        PaymentRow.status.in_(
                            (PaymentStatus.PENDING.value, PaymentStatus.PROCESSING.value)
                        ),
                    )
                    .order_by(PaymentRow.updated_at)
                    .limit(limit)
                )
            ).all()
            return [self._to_domain(row) for row in rows]

    async def get_by_provider_reference(
        self, provider: str, provider_reference: str
    ) -> Payment | None:
        """Resolve a provider callback to one payment without crossing provider boundaries."""
        async with self.database.sessions() as session:
            rows = (
                await session.scalars(
                    select(PaymentRow)
                    .where(
                        PaymentRow.provider == provider,
                        PaymentRow.provider_reference == provider_reference,
                    )
                    .limit(2)
                )
            ).all()
            if len(rows) > 1:
                raise RuntimeError("provider reference is ambiguous across tenants")
            return self._to_domain(rows[0]) if rows else None

    async def get(
        self, payment_id: str, tenant_id: str = "local"
    ) -> Payment | None:
        async with self.database.sessions() as session:
            row = await session.scalar(
                select(PaymentRow).where(
                    PaymentRow.id == payment_id,
                    PaymentRow.tenant_id == tenant_id,
                )
            )
            return self._to_domain(row) if row is not None else None

    async def authenticate_api_key(self, api_key: str) -> str | None:
        if not api_key:
            return None
        key_hash = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
        prefix = api_key[:24]
        async with self.database.sessions() as session:
            credentials = (
                await session.scalars(
                    select(ApiCredentialRow).where(
                        ApiCredentialRow.key_prefix == prefix,
                        ApiCredentialRow.revoked_at.is_(None),
                    )
                )
            ).all()
            for credential in credentials:
                if hmac.compare_digest(credential.key_hash, key_hash):
                    tenant = await session.get(TenantRow, credential.tenant_id)
                    if tenant is not None and tenant.status == "active":
                        return tenant.id
        return None


    async def revoke_api_key(self, tenant_id: str, key_prefix: str) -> bool:
        """Revoke one credential belonging to the specified tenant."""
        async with self.database.sessions() as session:
            async with session.begin():
                credential = await session.scalar(
                    select(ApiCredentialRow).where(
                        ApiCredentialRow.tenant_id == tenant_id,
                        ApiCredentialRow.key_prefix == key_prefix,
                        ApiCredentialRow.revoked_at.is_(None),
                    )
                )
                if credential is None:
                    return False
                credential.revoked_at = datetime.now(UTC)
                return True

    async def create_tenant(self, name: str) -> tuple[str, str]:
        if not name.strip() or len(name) > 128:
            raise ValueError("tenant name must contain 1 to 128 characters")
        tenant_id = str(uuid4())
        api_key = "fp_test_" + secrets.token_urlsafe(32)
        key_hash = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
        async with self.database.sessions() as session:
            async with session.begin():
                session.add(TenantRow(id=tenant_id, name=name.strip()))
                await session.flush()
                session.add(
                    ApiCredentialRow(
                        id=str(uuid4()),
                        tenant_id=tenant_id,
                        key_prefix=api_key[:24],
                        key_hash=key_hash,
                        label="Initial API key",
                    )
                )
        return tenant_id, api_key
