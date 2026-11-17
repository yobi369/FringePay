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

The API reserves a payment, idempotency key, and provider-dispatch outbox event in one database
transaction. The API and separate worker claim due events atomically. Failed attempts are scheduled
for retry, and expired processing leases can be recovered. This is still a sandbox-only workflow:
production adapters must use the stable payment ID as an external idempotency key and implement
provider-specific unknown-outcome handling before retries can safely touch a live rail.

Amounts are represented as integer minor units plus a three-letter uppercase currency code.
For Kenya shillings, callers should send the amount in cents (for example, KSh 10.50 is 1050
minor units). The API rejects floating-point amounts.

A sandbox success result is a simulated provider response. It is not evidence of settlement,
a bank credit, or movement of customer funds. Ledger journal primitives now validate balanced debit/credit entries, persist journal references
idempotently, and derive account balances from entries. They are not yet automatically connected
to payment or settlement events. The application layer does not expose journal mutation methods,
but database-level append-only enforcement and verified-settlement integration remain outstanding.
Production use requires tenant isolation, authenticated provider callbacks, durable outbox
processing, verified settlement reconciliation, security review, provider contracts and credentials,
and applicable regulatory/legal review.
