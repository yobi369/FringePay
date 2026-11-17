"""Domain validation for immutable, balanced double-entry journals."""

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum


class EntrySide(StrEnum):
    DEBIT = "debit"
    CREDIT = "credit"


@dataclass(frozen=True, slots=True)
class LedgerLine:
    account_code: str
    side: EntrySide
    amount_minor: int

    def __post_init__(self) -> None:
        if not self.account_code or len(self.account_code) > 64:
            raise ValueError("ledger account code must contain 1 to 64 characters")
        if not isinstance(self.side, EntrySide):
            raise ValueError("ledger entry side must be debit or credit")
        if (
            isinstance(self.amount_minor, bool)
            or not isinstance(self.amount_minor, int)
            or self.amount_minor <= 0
        ):
            raise ValueError("ledger entry amount must be a positive integer")


@dataclass(frozen=True, slots=True)
class Journal:
    reference: str
    currency: str
    description: str
    lines: tuple[LedgerLine, ...]

    def __post_init__(self) -> None:
        if not self.reference or len(self.reference) > 128:
            raise ValueError("journal reference must contain 1 to 128 characters")
        if not re.fullmatch(r"[A-Z]{3}", self.currency):
            raise ValueError("journal currency must be a three-letter uppercase ISO code")
        if len(self.description) > 256:
            raise ValueError("journal description cannot exceed 256 characters")
        if len(self.lines) < 2:
            raise ValueError("a journal requires at least two entries")
        codes = [line.account_code for line in self.lines]
        if len(codes) != len(set(codes)):
            raise ValueError("a journal cannot contain duplicate account codes")
        debits = sum(
            line.amount_minor for line in self.lines if line.side is EntrySide.DEBIT
        )
        credits = sum(
            line.amount_minor for line in self.lines if line.side is EntrySide.CREDIT
        )
        if debits != credits:
            raise ValueError("journal debits must equal credits")

    def fingerprint(self) -> str:
        payload = {
            "currency": self.currency,
            "description": self.description,
            "lines": sorted(
                (
                    line.account_code,
                    line.side.value,
                    line.amount_minor,
                )
                for line in self.lines
            ),
            "reference": self.reference,
        }
        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
