"""Validated provider settlement statement records."""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class SettlementStatus(StrEnum):
    MATCHED = "matched"
    UNMATCHED = "unmatched"
    PENDING = "pending"
    MISMATCH = "mismatch"


class SettlementConflict(ValueError):
    """Raised when a provider reference is reused with different statement data."""


@dataclass(frozen=True, slots=True)
class SettlementLine:
    provider_reference: str
    amount_minor: int
    currency: str
    settled_at: datetime
    source_reference: str

    def __post_init__(self) -> None:
        if not self.provider_reference or len(self.provider_reference) > 128:
            raise ValueError("provider reference must contain 1 to 128 characters")
        if (
            isinstance(self.amount_minor, bool)
            or not isinstance(self.amount_minor, int)
            or self.amount_minor <= 0
        ):
            raise ValueError("settlement amount must be a positive integer")
        if not re.fullmatch(r"[A-Z]{3}", self.currency):
            raise ValueError("settlement currency must be a three-letter ISO code")
        if self.settled_at.tzinfo is None:
            raise ValueError("settlement timestamp must include a timezone")
        if not self.source_reference or len(self.source_reference) > 128:
            raise ValueError("source reference must contain 1 to 128 characters")

    def fingerprint(self, provider: str) -> str:
        payload = {
            "amount_minor": self.amount_minor,
            "currency": self.currency,
            "provider": provider,
            "provider_reference": self.provider_reference,
            "settled_at": self.settled_at.isoformat(),
            "source_reference": self.source_reference,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
