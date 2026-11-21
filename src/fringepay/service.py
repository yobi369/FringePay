"""Application service for sandbox payment orchestration."""
from dataclasses import dataclass
from uuid import uuid4

from fringepay.domain import Money, Payment, PaymentStatus
from fringepay.providers import PaymentCommand, PaymentProvider


class IdempotencyConflict(Exception):
    """An idempotency key was reused with a different request."""


@dataclass(frozen=True, slots=True)
class CreatePayment:
    amount: Money
    reference: str
    phone_number: str | None = None


class PaymentService:
    """In-memory service for local development only; not multi-worker safe."""

    def __init__(self, provider: PaymentProvider) -> None:
        self.provider = provider
        self._payments: dict[str, Payment] = {}
        self._idempotency: dict[str, tuple[CreatePayment, str]] = {}

    async def create(self, request: CreatePayment, idempotency_key: str) -> Payment:
        if not idempotency_key or len(idempotency_key) > 128:
            raise ValueError("idempotency key must contain 1 to 128 characters")
        existing = self._idempotency.get(idempotency_key)
        if existing:
            previous_request, payment_id = existing
            if previous_request != request:
                raise IdempotencyConflict(
                    "idempotency key was already used for another request"
                )
            return self._payments[payment_id]
        payment_id = str(uuid4())
        command = PaymentCommand(
            payment_id=payment_id,
            amount=request.amount,
            reference=request.reference,
            phone_number=request.phone_number,
        )
        result = await self.provider.initiate(command)
        payment = Payment(
            id=payment_id,
            amount=request.amount,
            reference=request.reference,
            provider=result.provider,
            provider_reference=result.provider_reference,
            status=result.status,
            phone_number=request.phone_number,
        )
        self._payments[payment.id] = payment
        self._idempotency[idempotency_key] = (request, payment.id)
        return payment

    def apply_provider_status(
        self, payment_id: str, new_status: PaymentStatus
    ) -> Payment:
        """Apply a provider status update only when lifecycle rules allow it."""
        payment = self.get(payment_id)
        if payment is None:
            raise KeyError(f"payment not found: {payment_id}")
        updated = payment.transition_to(new_status)
        self._payments[payment_id] = updated
        return updated

    def get(self, payment_id: str) -> Payment | None:
        return self._payments.get(payment_id)
