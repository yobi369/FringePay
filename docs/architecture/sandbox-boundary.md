# Sandbox boundary

FringePay currently runs a deterministic **sandbox adapter only**. It does not connect to
Safaricom Daraja, Airtel Money, a bank, a card network, or any other live payment rail.

The HTTP API persists payment and idempotency records through an async SQLAlchemy repository.
SQLite is the local default; PostgreSQL is supported through the async driver. The initial
Alembic migration defines the payment and idempotency tables. Development may create schema
automatically; deployed environments must apply versioned migrations.

Payment reservation and idempotency-key insertion occur in one database transaction. The
unique idempotency key prevents concurrent requests from reserving separate payments for the
same key. A request with the same key but a different canonical payload is rejected. Tenant records and hashed, revocable API credentials are implemented. Payment retrieval and
idempotency records are tenant-scoped; credentials are resolved to a tenant before payment routes
run. The current model has no role-based permissions, credential scopes, per-tenant rate limits,
or tenant-specific provider configuration. Ledger accounts and journals are still global and
must be tenant-scoped before ledger APIs are exposed.

The API reserves a payment, idempotency key, and provider-dispatch outbox event in one database
transaction. The API and separate worker claim due events atomically. Failed attempts use bounded exponential backoff and move to a dead-letter state after the
configured attempt limit; expired processing leases can be recovered. This is still a sandbox-only workflow:
production adapters must use the stable payment ID as an external idempotency key and implement
provider-specific unknown-outcome handling before retries can safely touch a live rail.

Amounts are represented as integer minor units plus a three-letter uppercase currency code.
For Kenya shillings, callers should send the amount in cents (for example, KSh 10.50 is 1050
minor units). The API rejects floating-point amounts.

A sandbox success result is a simulated provider response. It is not evidence of settlement,
a bank credit, or movement of customer funds. Provider callbacks now have a sandbox-only timestamped HMAC-SHA256 verifier and durable event-ID
replay protection. The signature scheme is an internal sandbox contract, not a provider-specific
integration. Ledger journal primitives validate balanced debit/credit entries, persist journal references
idempotently per tenant, and derive account balances from entries. Tenant-scoped settlement
records can match provider references against succeeded payments and classify rows as matched,
pending, unmatched, or mismatch. Statement-file ingestion and settlement-triggered ledger
postings are not yet implemented; no sandbox event is treated as actual settlement. The application layer does not expose journal mutation methods,
but database-level append-only enforcement and verified-settlement integration remain outstanding.
Production use still requires finer-grained authorization, per-tenant rate limiting, tenant-scoped
ledger and provider configuration, authenticated provider-specific callbacks, durable outbox
processing, verified settlement reconciliation, security review, provider contracts and credentials,
and applicable regulatory/legal review.
