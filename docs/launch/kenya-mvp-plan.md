# FringePay Kenya MVP launch plan

## Product position

FringePay is a provider-independent payment orchestration platform for African businesses. It is not a replacement for Safaricom's payment network and must not claim to be a licensed payment service provider. Its initial product is a unified API and operational layer that connects merchants to authorized payment providers.

## Launch strategy

Launch in controlled stages. Do not enable live-money processing until provider approval, legal/regulatory review, security review, operational readiness, and reconciliation controls are complete.

### Stage 0 — Engineering release candidate

- Keep the current sandbox-only API explicitly labelled as sandbox.
- Make PostgreSQL the required deployment database and run Alembic migrations as a release step.
- Separate API request handling from provider dispatch; the durable outbox worker is the only dispatcher.
- Add readiness checks for database and worker state, structured logs, request correlation, metrics, and safe error responses.
- Add rate limits, credential rotation, tenant suspension, audit events, and secure production configuration.
- Add automated tests for idempotency races, outbox lease recovery, callback replay, tenant isolation, and failure recovery.

Exit criteria: reproducible deployment, green CI including PostgreSQL tests, no production secrets in source, documented rollback and backup procedures.

### Stage 1 — First rail: M-Pesa via Daraja

- Implement a dedicated Daraja adapter behind the provider contract.
- Start with Daraja sandbox and STK Push; add callback validation, transaction status queries, timeout handling, and reconciliation.
- Store provider request/response metadata with strict data minimization and redaction.
- Use the stable FringePay payment ID as the provider-side idempotency/correlation reference wherever supported.
- Treat callback status and settlement evidence as distinct states. Never infer settlement from an initiation response.

Exit criteria: repeatable sandbox test suite covering success, cancellation, timeout, duplicate callbacks, invalid callbacks, delayed callbacks, and provider outage.

### Stage 2 — Merchant pilot

- Merchant onboarding and scoped API credentials.
- Minimal merchant portal: transactions, status, refunds (only if supported), API keys, webhook endpoints, and reconciliation exports.
- Webhook delivery with signing, retries, replay controls, and delivery history.
- Pilot with a small number of merchants under approved provider arrangements and explicit transaction limits.

Exit criteria: monitored pilot, daily reconciliation, incident response contact, support workflow, and documented merchant terms.

### Stage 3 — Multi-provider platform

- Provider registry and capability discovery.
- Provider routing rules and safe failover only when the original attempt is known not to have been accepted.
- Additional authorized providers and payment methods.
- Unified fees, settlement reporting, ledger posting, refunds/reversals, and FX only after the first rail is stable.

## Non-negotiable payment invariants

1. A client retry with the same tenant and idempotency key must not create a second payment.
2. A provider timeout is an unknown outcome, not proof of failure; never blindly initiate a second charge.
3. Provider callbacks must be authenticated, replay-safe, correlated to the correct provider and payment, and transition-validated.
4. Initiated, provider-confirmed, and settled are different concepts.
5. Ledger entries are append-only; corrections use compensating entries.
6. Every merchant query and mutation is tenant-scoped.
7. Secrets and personal/payment data are never written to logs.
8. Live processing remains disabled until provider and regulatory requirements are confirmed.

## Current known boundary

The existing foundation has a FastAPI API, SQLAlchemy persistence, migrations, tenant API credentials, durable idempotency, an outbox and worker, a sandbox adapter, webhook replay protection, ledger primitives, and settlement matching. It is not yet a live payment gateway: the API/worker currently use the sandbox adapter, payment lifecycle events are not automatically posted to the ledger, and no Daraja integration or merchant portal is present.

## Release discipline

- Keep main as the stable release line.
- Develop through small, reviewable pull requests.
- Every milestone must pass Ruff, unit tests, PostgreSQL integration/concurrency tests, migration checks, and a documented manual acceptance checklist.
- Do not merge a milestone based only on a green lint job or a sandbox happy path.
