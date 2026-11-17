"""Async SQLAlchemy persistence and transactional idempotency primitives."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from fringepay.domain import Money, Payment, PaymentStatus
from fringepay.ledger import EntrySide, Journal
from fringepay.service import CreatePayment


class Base(DeclarativeBase):
    """Base metadata for FringePay persistence models."""


class PaymentRow(Base):
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    reference: Mapped[str] = mapped_column(String(128), nullable=False)
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

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    normal_side: Mapped[str] = mapped_column(String(6), nullable=False)


class LedgerTransactionRow(Base):
    __tablename__ = "ledger_transactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    reference: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    description: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class LedgerEntryRow(Base):
    __tablename__ = "ledger_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    transaction_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ledger_transactions.id", ondelete="RESTRICT")
    )
    account_code: Mapped[str] = mapped_column(
        String(64), ForeignKey("ledger_accounts.code", ondelete="RESTRICT")
    )
    side: Mapped[str] = mapped_column(String(6), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
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
        """Create tables for local development and tests.

        Production schema changes must be applied through versioned migrations.
        """
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        await self.engine.dispose()


class PaymentRepository:
    """Durable payment storage with a database-enforced idempotency key."""

    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _request_hash(request: CreatePayment) -> str:
        payload = {
            "amount_minor": request.amount.minor_units,
            "currency": request.amount.currency,
            "reference": request.reference,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _to_domain(row: PaymentRow) -> Payment:
        return Payment(
            id=row.id,
            amount=Money(row.amount_minor, row.currency),
            reference=row.reference,
            provider=row.provider,
            provider_reference=row.provider_reference,
            status=PaymentStatus(row.status),
        )

    async def reserve(
        self,
        request: CreatePayment,
        idempotency_key: str,
        provider: str = "sandbox",
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
                    existing = await session.get(IdempotencyRow, idempotency_key)
                    if existing is not None:
                        if existing.request_hash != request_hash:
                            raise PersistentIdempotencyConflict(
                                "idempotency key was already used for another request"
                            )
                        row = await session.get(PaymentRow, existing.payment_id)
                        if row is None:
                            raise RuntimeError("idempotency record has no payment")
                        return self._to_domain(row), False

                    payment_id = str(uuid4())
                    row = PaymentRow(
                        id=payment_id,
                        amount_minor=request.amount.minor_units,
                        currency=request.amount.currency,
                        reference=request.reference,
                        provider=provider,
                        provider_reference=None,
                        status=PaymentStatus.PENDING.value,
                    )
                    session.add(row)
                    session.add(
                        IdempotencyRow(
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
                existing = await session.get(IdempotencyRow, idempotency_key)
                if existing is None:
                    raise
                if existing.request_hash != request_hash:
                    raise PersistentIdempotencyConflict(
                        "idempotency key was already used for another request"
                    ) from None
                row = await session.get(PaymentRow, existing.payment_id)
                if row is None:
                    raise RuntimeError("idempotency record has no payment") from None
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
        """Make abandoned processing leases eligible for safe idempotent retry."""
        now = datetime.now(UTC)
        cutoff = now - timedelta(seconds=stale_after_seconds)
        async with self.database.sessions() as session:
            async with session.begin():
                result = await session.execute(
                    update(ProviderDispatchOutboxRow)
                    .where(
                        ProviderDispatchOutboxRow.status == "processing",
                        ProviderDispatchOutboxRow.locked_at < cutoff,
                    )
                    .values(
                        status="retry",
                        available_at=now,
                        locked_at=None,
                        last_error_code="dispatch_lease_expired",
                        updated_at=now,
                    )
                )
                return result.rowcount or 0

    async def retry_dispatch(
        self, outbox_id: str, error_code: str, retry_delay_seconds: int = 5
    ) -> None:
        """Schedule a claimed event for retry without storing exception details."""
        async with self.database.sessions() as session:
            async with session.begin():
                event = await session.get(ProviderDispatchOutboxRow, outbox_id)
                if event is None or event.status != "processing":
                    raise ValueError("dispatch event is not claimed")
                now = datetime.now(UTC)
                event.status = "retry"
                event.available_at = now + timedelta(seconds=retry_delay_seconds)
                event.locked_at = None
                event.last_error_code = error_code[:64]
                event.updated_at = now


    async def create_ledger_account(
        self, code: str, name: str, currency: str, normal_side: EntrySide
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
                existing = await session.get(LedgerAccountRow, code)
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
                        code=code,
                        name=name,
                        currency=currency,
                        normal_side=normal_side.value,
                    )
                )

    async def post_journal(self, journal: Journal) -> tuple[str, bool]:
        """Post a balanced journal once, using its reference as an idempotency key."""
        request_hash = journal.fingerprint()
        try:
            async with self.database.sessions() as session:
                async with session.begin():
                    existing = await session.scalar(
                        select(LedgerTransactionRow).where(
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
                        account = await session.get(LedgerAccountRow, line.account_code)
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
                            reference=journal.reference,
                            request_hash=request_hash,
                            currency=journal.currency,
                            description=journal.description,
                        )
                    )
                    for line in journal.lines:
                        session.add(
                            LedgerEntryRow(
                                id=str(uuid4()),
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

    async def account_balance(self, account_code: str) -> int:
        async with self.database.sessions() as session:
            account = await session.get(LedgerAccountRow, account_code)
            if account is None:
                raise KeyError(f"ledger account not found: {account_code}")
            debit_total = await session.scalar(
                select(func.coalesce(func.sum(LedgerEntryRow.amount_minor), 0)).where(
                    LedgerEntryRow.account_code == account_code,
                    LedgerEntryRow.side == EntrySide.DEBIT.value,
                )
            )
            credit_total = await session.scalar(
                select(func.coalesce(func.sum(LedgerEntryRow.amount_minor), 0)).where(
                    LedgerEntryRow.account_code == account_code,
                    LedgerEntryRow.side == EntrySide.CREDIT.value,
                )
            )
            if account.normal_side == EntrySide.DEBIT.value:
                return int(debit_total) - int(credit_total)
            return int(credit_total) - int(debit_total)

    async def get(self, payment_id: str) -> Payment | None:
        async with self.database.sessions() as session:
            row = await session.get(PaymentRow, payment_id)
            return self._to_domain(row) if row is not None else None
