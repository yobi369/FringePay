# FringePay

**Provider-independent payment orchestration for African applications.**

FringePay provides one API and operational layer for applications and merchants integrating with multiple authorized payment providers. Providers execute the regulated payment rails; FringePay manages payment orchestration, transaction state, idempotency, webhooks, ledgering, reconciliation, and operational controls.

> **Current release status: sandbox-only engineering release candidate.** No live provider adapter or live-money processing is enabled. The current API reserves payments and queues durable dispatch work; the separate worker is the only component that calls a provider adapter.

## Product direction

Start in Kenya with M-Pesa through an approved Daraja integration, then expand to additional authorized payment providers and markets. FringePay is an orchestration platform, not a replacement for Safaricom's payment network, a bank, or a wallet issuer.

## Implemented foundation

- FastAPI payment creation and retrieval endpoints.
- Deterministic sandbox provider adapter; no real payment rail is called.
- SQLAlchemy 2 async persistence and Alembic migrations.
- PostgreSQL support and SQLite local development support.
- Tenant-scoped API credentials stored as SHA-256 hashes, revocation, and tenant-isolated payment reads.
- Durable tenant-scoped idempotency with payload-conflict detection.
- Transactional provider-dispatch outbox with atomic claims, bounded exponential retries, dead-letter handling, and expired-lease recovery.
- Separate worker command for dispatching outbox events (sandbox adapter only).
- Payment lifecycle transition validation.
- Double-entry journal validation and tenant-scoped persistence with idempotent journal references and derived account balances.
- Tenant-scoped settlement matching with duplicate detection and matched, pending, unmatched, and mismatch outcomes.
- Timestamped HMAC-SHA256 verification and replay protection for sandbox callbacks.
- Strict integer validation for monetary minor units.

## Important implementation boundary

The payment creation endpoint reserves a payment and outbox event in one database transaction, then returns HTTP 202 Accepted. It does not call the provider inside the HTTP request. The worker claims the outbox event and dispatches it. A repeated request with the same tenant, idempotency key, and payload returns the existing payment; reusing the key with a different payload returns HTTP 409.

A provider timeout is an unknown outcome, not proof that a charge failed. Provider adapters must use the stable FringePay payment ID as their provider-side idempotency/correlation reference wherever supported. The ledger is currently a separate journal subsystem: payment status changes do not automatically post ledger entries, and a provider callback is not settlement evidence.

## Architecture

    Client applications
            |
            v
    FringePay API ---- Authentication / tenant boundary
            |
            v
    Payment reservation + idempotency
            |
            v
    Transactional provider outbox
            |
            v
    Background worker
            |
            v
    Provider adapter contract
      |             |              |
      v             v              v
    Sandbox       Daraja*       Other providers*
            |
            v
    Verified callbacks / ledger / reconciliation / audit

*Provider integrations require approved credentials, contracts, and compliance review.*

## Technology

- Python 3.11+
- FastAPI, Pydantic, SQLAlchemy 2 async
- PostgreSQL (production target); SQLite (local default)
- Alembic migrations
- Pytest, Ruff, GitHub Actions
- Docker Compose for local PostgreSQL

## Local development

    python -m venv .venv
    source .venv/bin/activate
    python -m pip install -e ".[dev]"
    cp .env.example .env
    uvicorn fringepay.main:app --reload

By default, development uses local SQLite at ./fringepay.db; the development app creates its schema automatically. For PostgreSQL, start the local service:

    docker compose up -d postgres

Then set FRINGEPAY_DATABASE_URL in .env to:

    postgresql+asyncpg://fringepay:localdev_only_change_me@localhost:5432/fringepay

Apply versioned migrations before running a deployment that does not auto-create tables:

    alembic upgrade head

The local compose password is for development only. Replace it and use managed secrets for any shared environment. Local development seeds a tenant and the local-only key local-development-key. For a deployed environment, apply migrations and run fringepay-admin create-tenant --name "Merchant Name"; the random API key is displayed once and must be stored in a secret manager. Revoke a credential with fringepay-admin revoke-api-key --tenant-id TENANT_ID --key-prefix KEY_PREFIX.

In a second terminal, run fringepay-worker to drain pending sandbox outbox events. The current worker is sandbox-only.

## API

- GET /health — process health only; it does not prove database/provider readiness.
- GET /ready — checks connectivity to the configured database.
- GET /v1/status — confirms sandbox-only mode.
- POST /v1/payments — reserve a sandbox payment and queue dispatch; returns HTTP 202. Requires X-API-Key and Idempotency-Key headers plus JSON body with amount_minor, currency, and reference.
- GET /v1/payments/{payment_id} — retrieve a persisted payment; requires X-API-Key.
- POST /v1/webhooks/sandbox — accept a signed sandbox status callback; requires X-Provider-Event-Id and X-FringePay-Signature, not the client API key.

Example request:

    curl -i -X POST http://127.0.0.1:8000/v1/payments       -H "Content-Type: application/json"       -H "X-API-Key: local-development-key"       -H "Idempotency-Key: local-order-001"       -d '{"amount_minor":1250,"currency":"KES","reference":"order-001"}'

For KES, amount_minor is cents: KSh 10.50 is represented as 1050. A 202 response means the payment was accepted for asynchronous processing, not that the provider accepted or settled it.

The sandbox webhook secret is configured with FRINGEPAY_SANDBOX_WEBHOOK_SECRET. The signature header format is t=<unix_timestamp>,v1=<hex_hmac_sha256>, calculated over the timestamp, a dot, and the exact raw request body. The default timestamp tolerance is 300 seconds. This generic scheme is a sandbox contract, not a claim of compatibility with any specific provider signature.

## Launch milestones

See the Kenya MVP launch plan at docs/launch/kenya-mvp-plan.md for the release stages, acceptance criteria, and payment safety invariants. The Daraja sandbox setup and STK Push flow are documented in docs/integrations/daraja-sandbox.md.

## Safety and scope

FringePay is not a bank, wallet issuer, payment scheme, or substitute for provider authorization. A sandbox success result is not evidence of settlement or movement of customer funds. Live processing must remain disabled until provider approval, legal/regulatory assessment, security review, reconciliation, operational controls, and applicable licensing obligations are addressed.

## Quality checks

    ruff check .
    pytest

Never commit credentials, private keys, production customer data, or real payment secrets.

## License

License selection is intentionally pending until the owner confirms the intended distribution and commercial model.
