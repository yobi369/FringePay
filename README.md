# FringePay

**Provider-independent payment orchestration for African applications.**

FringePay is an API and orchestration layer designed to give applications one consistent
interface to multiple authorized payment providers. FringePay owns the integration abstractions,
transaction lifecycle, ledger, reconciliation, webhook delivery, and operational controls;
external providers remain responsible for executing regulated payment rails.

> **Current status:** Early sandbox foundation. The HTTP API now stores payment and idempotency
> records through SQLAlchemy. No live-money processing or live provider integration is enabled.

## Design principles

- **Provider independence:** application code depends on a stable internal contract, not a provider SDK.
- **Explicit money semantics:** amounts use integer minor units and ISO currency codes; never floats.
- **Ledger integrity:** immutable, balanced double-entry postings; corrections use compensating entries.
- **Idempotency:** database uniqueness prevents duplicate reservations for the same key.
- **Observable state:** payment transitions are explicit, validated, timestamped, and auditable.
- **Secure by default:** secrets stay outside source control; webhooks are authenticated; sensitive data is minimized.
- **Honest capability boundaries:** sandbox simulations are not settlement evidence.

## Current implementation

- FastAPI payment creation and retrieval endpoints.
- Deterministic sandbox provider adapter; no real payment rail is called.
- SQLAlchemy 2 async persistence for payments and idempotency keys.
- SQLite local default and PostgreSQL async driver support.
- Alembic versioned schema migrations.
- Transactional provider-dispatch outbox with atomic claims, retry scheduling, and expired-lease recovery.
- Separate worker command for draining due outbox events (currently sandbox adapter only).
- Strict integer validation for monetary minor units.
- Lifecycle transition validation and CI lint/test checks.

The HTTP request reserves a payment, idempotency key, and provider-dispatch outbox event in one
database transaction. A repeated request with the same key and payload returns the existing
payment; a changed payload returns HTTP 409. The API and a separate worker compete for events
using atomic database claims, and abandoned processing leases can be retried. Provider adapters
must use the stable payment ID as their external idempotency reference before live integrations.

## Planned architecture

```text
Client applications
        |
        v
FringePay API ---- Authentication / tenant boundary
        |
        v
Payment orchestration
  |          |             |
  v          v             v
Routing   State machine  Idempotency
        |
        v
Provider adapter contract
  |             |                |
  v             v                v
Sandbox      Daraja*          Other providers*
        |
        v
Ledger / Webhook outbox / Reconciliation / Audit log

*Provider integrations require approved credentials, contracts, and compliance review.
```

## Technology

- Python 3.11+
- FastAPI, Pydantic, SQLAlchemy 2 async
- PostgreSQL (production target); SQLite (local default)
- Alembic migrations
- Pytest, Ruff, GitHub Actions
- Docker Compose for local PostgreSQL

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env
uvicorn fringepay.main:app --reload
```

By default, development uses local SQLite at `./fringepay.db`; the development app creates its
schema automatically. For PostgreSQL, start the local service:

```bash
docker compose up -d postgres
```

Then set `FRINGEPAY_DATABASE_URL` in `.env` to:

```text
postgresql+asyncpg://fringepay:localdev_only_change_me@localhost:5432/fringepay
```

Apply versioned migrations before running a deployment that does not auto-create tables:

```bash
alembic upgrade head
```

The local compose password is for development only. Replace it and use managed secrets for
any shared environment. In a second terminal, run `fringepay-worker` to drain pending sandbox
outbox events; it is designed to run as a separate process in a deployment.

## API

- `GET /health` — process health only; it does not prove database/provider readiness.
- `GET /v1/status` — confirms sandbox-only mode.
- `POST /v1/payments` — create a simulated payment. Requires an `Idempotency-Key` header and
  JSON body with `amount_minor`, `currency`, and `reference`.
- `GET /v1/payments/{payment_id}` — retrieve a persisted payment.

Example:

```bash
curl -X POST http://127.0.0.1:8000/v1/payments \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: local-order-001" \
  -d '{"amount_minor":1250,"currency":"KES","reference":"order-001"}'
```

For KES, `amount_minor` is cents: KSh 10.50 is represented as 1050.

## Development milestones

1. Repository foundation, domain models, configuration, and CI.
2. Provider interface and deterministic sandbox adapter.
3. Durable payment storage, idempotency, API integration, and lifecycle state machine.
4. Harden outbox recovery, provider idempotency, and PostgreSQL concurrency behavior.
5. Immutable double-entry ledger with balance invariants.
6. Signed webhook delivery, replay protection, and reconciliation.
7. Tenant authentication, authorization, auditability, and operational controls.
8. Authorized provider adapters in sandbox/test environments.
9. Security, compliance, load, and failure-mode hardening before any live-money pilot.

## Safety and scope

FringePay is not a bank, wallet issuer, payment scheme, or substitute for provider authorization.
A sandbox success result is not evidence of settlement or movement of customer funds. Live
processing must remain disabled until provider approval, legal/regulatory assessment, security
review, reconciliation, operational controls, and applicable licensing obligations are addressed.

## Quality checks

```bash
ruff check .
pytest
```

Never commit credentials, private keys, production customer data, or real payment secrets.

## License

License selection is intentionally pending until the owner confirms the intended distribution
and commercial model.
