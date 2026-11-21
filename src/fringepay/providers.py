"""Provider adapter contract and sandbox implementation."""
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from fringepay.domain import Money, PaymentStatus


@dataclass(frozen=True, slots=True)
class PaymentCommand:
    payment_id: str
    amount: Money
    reference: str
    phone_number: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderResult:
    provider: str
    provider_reference: str | None
    status: PaymentStatus


class ProviderTemporaryError(RuntimeError):
    """A provider call failed before a payment request could be submitted."""


class ProviderOutcomeUnknown(RuntimeError):
    """A provider may have accepted a request, but its response was not received."""


class ProviderRejected(ValueError):
    """A provider definitively rejected a payment initiation request."""


class PaymentProvider(Protocol):
    name: str

    async def initiate(self, command: PaymentCommand) -> ProviderResult:
        """Initiate a payment through this provider."""


class SandboxOutcome(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class SandboxProvider:
    """Deterministic test adapter; it never moves real money."""

    name = "sandbox"

    def __init__(self, outcome: SandboxOutcome = SandboxOutcome.PENDING) -> None:
        self.outcome = outcome

    async def initiate(self, command: PaymentCommand) -> ProviderResult:
        return ProviderResult(
            provider=self.name,
            provider_reference=f"sandbox_{command.payment_id}",
            status=PaymentStatus(self.outcome.value),
        )
