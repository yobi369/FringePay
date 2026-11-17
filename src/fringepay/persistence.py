"""Async SQLAlchemy persistence and transactional idempotency primitives."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from fringepay.domain import Money, Payment, PaymentStatus
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
                    )
                row = await session.get(PaymentRow, existing.payment_id)
                if row is None:
                    raise RuntimeError("idempotency record has no payment")
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
                return updated

    async def get(self, payment_id: str) -> Payment | None:
        async with self.database.sessions() as session:
            row = await session.get(PaymentRow, payment_id)
            return self._to_domain(row) if row is not None else None
