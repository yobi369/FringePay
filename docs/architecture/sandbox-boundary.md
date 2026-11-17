# Sandbox boundary

FringePay currently runs a deterministic **sandbox adapter only**. It does not connect to
Safaricom Daraja, Airtel Money, a bank, a card network, or any other live payment rail.

The HTTP API persists payment and idempotency records through an async SQLAlchemy repository.
SQLite is the local default; PostgreSQL is supported through the async driver. The initial
Alembic migration defines the payment and idempotency tables. Development may create schema
automatically; deployed environments must apply versioned migrations.

Payment reservation and idempotency-key insertion occur in one database transaction. The
unique idempotency key prevents concurrent requests from reserving separate payments for the
same key. A request with the same key but a different canonical payload is rejected. Keys are
currently global, not tenant-scoped; tenant authentication and key scoping are not implemented.

The API reserves a payment before invoking the sandbox adapter. A process crash after reservation
but before provider execution can leave a pending record. A transactional outbox, dispatch worker,
retry policy, and explicit unknown-outcome handling are required before relying on this pattern
for external provider calls.

Amounts are represented as integer minor units plus a three-letter uppercase currency code.
For Kenya shillings, callers should send the amount in cents (for example, KSh 10.50 is 1050
minor units). The API rejects floating-point amounts.

A sandbox success result is a simulated provider response. It is not evidence of settlement,
a bank credit, or movement of customer funds. Production use requires tenant isolation,
authenticated provider callbacks, durable outbox processing, immutable ledger postings,
reconciliation, security review, provider contracts and credentials, and applicable
regulatory/legal review.
