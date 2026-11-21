"""Core payment domain types. Monetary values are integer minor units."""
import re
from dataclasses import dataclass, replace
from enum import StrEnum

_CURRENCY = re.compile(r"^[A-Z]{3}$")


@dataclass(frozen=True, slots=True)
class Money:
    minor_units: int
    currency: str

    def __post_init__(self) -> None:
        if (
            isinstance(self.minor_units, bool)
            or not isinstance(self.minor_units, int)
            or self.minor_units < 0
        ):
            raise ValueError("minor_units must be a non-negative integer")
        if not _CURRENCY.fullmatch(self.currency):
            raise ValueError("currency must be a three-letter uppercase ISO code")

    def __add__(self, other: "Money") -> "Money":
        self._require_same_currency(other)
        return Money(self.minor_units + other.minor_units, self.currency)

    def _require_same_currency(self, other: "Money") -> None:
        if self.currency != other.currency:
            raise ValueError("cannot combine different currencies")


class PaymentStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class InvalidPaymentTransition(ValueError):
    """Raised when a payment status change violates the lifecycle rules."""


_ALLOWED_TRANSITIONS: dict[PaymentStatus, frozenset[PaymentStatus]] = {
    PaymentStatus.PENDING: frozenset(
        {
            PaymentStatus.PROCESSING,
            PaymentStatus.SUCCEEDED,
            PaymentStatus.FAILED,
            PaymentStatus.CANCELLED,
        }
    ),
    PaymentStatus.PROCESSING: frozenset(
        {
            PaymentStatus.SUCCEEDED,
            PaymentStatus.FAILED,
            PaymentStatus.CANCELLED,
        }
    ),
    PaymentStatus.SUCCEEDED: frozenset(),
    PaymentStatus.FAILED: frozenset(),
    PaymentStatus.CANCELLED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class Payment:
    id: str
    amount: Money
    reference: str
    provider: str
    provider_reference: str | None
    status: PaymentStatus

    def __post_init__(self) -> None:
        if self.amount.minor_units <= 0:
            raise ValueError("payment amount must be greater than zero")
        if not self.id or not self.reference:
            raise ValueError("payment id and reference are required")

    def transition_to(self, new_status: PaymentStatus) -> "Payment":
        """Return a new payment with a valid lifecycle transition."""
        if new_status is self.status:
            return self
        if new_status not in _ALLOWED_TRANSITIONS[self.status]:
            raise InvalidPaymentTransition(
                f"payment cannot transition from {self.status.value} "
                f"to {new_status.value}"
            )
        return replace(self, status=new_status)
