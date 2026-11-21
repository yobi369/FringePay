# ADR 0002: Money and ledger invariants

- **Status:** Accepted for the initial implementation
- **Date:** 2026-11-17

## Decision

- Represent amounts as positive integer minor units plus an ISO 4217 currency code.
- Never use binary floating-point values for money.
- Ledger journals are immutable after posting.
- Every posted journal must balance per currency: total debits equal total credits.
- Correct posted entries with compensating journals, not destructive edits.
- A payment status is not proof of settlement; preserve provider references and reconciliation evidence separately.

## Consequences

These invariants shape the domain model, database constraints, API validation, and tests. Currency exponent handling must be explicit; do not assume every currency has two decimal places.
