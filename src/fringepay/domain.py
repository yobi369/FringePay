"""Core payment domain types. Monetary values are integer minor units."""
from dataclasses import dataclass
from enum import StrEnum
import re

_CURRENCY = re.compile(r"^[A-Z]{3}$")

@dataclass(frozen=True, slots=True)
class Money:
    minor_units: int
    currency: str

    def __post_init__(self) -> None:
        if isinstance(self.minor_units, bool) or self.minor_units < 0:
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
