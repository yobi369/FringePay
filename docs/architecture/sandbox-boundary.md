# Sandbox boundary

FringePay currently runs a deterministic **sandbox adapter only**. It does not connect to
Safaricom Daraja, Airtel Money, a bank, a card network, or any other live payment rail.

The HTTP API still uses the original in-memory application service. A separate async SQLAlchemy
persistence layer now provides durable payment rows and database-enforced idempotency primitives;
it is covered by SQLite restart tests but is not yet wired into the HTTP routes. The API therefore
still loses its current payment state on restart and must not be treated as production-ready. The
persistence layer also needs versioned migrations and concurrency tests against PostgreSQL before
it can be considered production-grade.

Amounts are represented as integer minor units plus a three-letter uppercase currency code.
For Kenya shillings, callers should send the amount in cents (for example, KSh 10.50 is 1050
minor units). The API never accepts floating-point monetary values.

A sandbox success result is a simulated provider response. It is not evidence of settlement,
a bank credit, or a movement of customer funds. Production use requires durable persistence,
transactional idempotency, authenticated tenants, authorization, provider contracts and
credentials, signed callback verification, reconciliation, security review, and applicable
regulatory/legal review.
