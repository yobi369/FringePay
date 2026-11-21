# FringePay Kenya MVP launch plan

## Product position

FringePay is a provider-independent payment orchestration platform for African applications and merchants. It is not a replacement for Safaricom's payment network, a bank, or a wallet issuer. Payment rails are executed by authorized providers; FringePay supplies the API, orchestration, transaction controls, webhooks, ledgering, and reconciliation layer.

## Release status — 21 November 2026

**Current milestone: sandbox integration preview. Not a live payment gateway.**

Completed in the repository:
- FastAPI payment API with tenant-scoped API credentials and payment retrieval.
- PostgreSQL persistence, versioned Alembic migrations, idempotency, transactional outbox, and a separate worker.
- Sandbox provider and a Daraja sandbox STK Push adapter with OAuth, phone-number validation, callback correlation, callback-token authentication, provider status query, and worker reconciliation.
- Unknown provider outcomes are quarantined rather than blindly retried.
- PII phone-number encryption support, required by production configuration.
- Double-entry journal primitives and settlement matching primitives.
- Docker image, PostgreSQL/API/worker Compose stack, deployment runbook, and CI checks.
- Latest main-branch CI run passed Ruff, pytest (including PostgreSQL service tests), Docker Compose validation, and image build.

Not yet proven:
- A complete end-to-end run against the user's own Daraja sandbox app and shortcode.
- Live operational availability, real-world load, security penetration testing, production incident response, or merchant support.
- Automated M-Pesa receipt ingestion and settlement statement reconciliation.
- Automatic posting of every payment lifecycle event to the financial ledger.
- Merchant-facing portal, outbound merchant webhooks, refunds/reversals, and additional provider rails.
- Legal/regulatory and provider approval for any commercial live-money operating model.

## Launch strategy

Launch the product quickly as a **sandbox integration preview** for technical demonstrations and early partner conversations. Do not describe it as a live payment gateway, accept real customer funds, or enable live provider endpoints until provider approval, legal/regulatory review, security review, operational readiness, and reconciliation controls are complete.

### Milestone A — Sandbox integration preview

- Deploy the API and worker as separate always-on services using the same immutable image.
- Use managed PostgreSQL, TLS, a secret manager, encrypted phone storage, and Alembic migrations as a release step.
- Run end-to-end tests with an approved Daraja sandbox app: success, cancellation, delayed callback, duplicate callback, invalid callback token, provider outage, and ambiguous timeout.
- Verify the callback URL is publicly reachable over HTTPS and its query token is redacted from all proxy/platform logs.
- Create a dedicated demo tenant and scoped API key; never use the local development key for a shared environment.
- Publish an OpenAPI integration guide and clearly label the environment as sandbox.
- Add monitoring for API readiness, worker heartbeat/queue age, provider status-query failures, unknown outcomes, and database health.
- Document backup/restore, rollback, credential rotation, support contact, and incident response.

Exit criteria: reproducible sandbox deployment, real Daraja sandbox transaction verified end-to-end, no unresolved critical/high security findings, green CI, and documented recovery procedure.

### Milestone B — Controlled merchant pilot readiness

- Merchant onboarding and scoped API credentials, credential rotation, suspension, and audit trail.
- Minimal merchant portal for transactions, payment status, API keys, webhook endpoints, and reconciliation exports.
- Signed outbound merchant webhooks with retries, replay controls, delivery history, and dead-letter handling.
- Durable provider request/response metadata with data minimization and redaction.
- Complete financial lifecycle integration: payment state changes, journal posting, fee accounting, reversals, settlement records, and reconciliation evidence.
- Daily reconciliation and an exception queue with human review.
- Explicit pilot transaction limits, support workflow, merchant terms, privacy notice, and incident response.

Exit criteria: security review, operational runbook, provider-approved pilot scope, verified daily reconciliation, and no unresolved critical payment correctness defects.

### Milestone C — Authorized live-money operation

- Obtain written provider approval for the exact merchant/service model and production credentials.
- Obtain Kenyan legal/regulatory advice and confirm whether the actual orchestration, processing, custody, settlement, and data flows require CBK authorization or other approvals.
- Keep funds with authorized payment providers/banks unless the company has the required authorization and controls to do otherwise.
- Complete independent security testing, disaster recovery, key rotation, data retention/deletion, access review, and ongoing monitoring.
- Enable production rails only after documented sign-off and a limited, monitored pilot.

### Milestone D — Multi-provider platform

- Provider registry, capability discovery, provider health, and routing rules.
- Safe failover only when the original provider attempt is known not to have been accepted.
- Additional authorized providers and payment methods in Kenya and other African markets.
- Unified fee schedules, settlement reporting, ledger posting, refunds/reversals, and FX after the first rail is stable.

## Non-negotiable payment invariants

1. A client retry with the same tenant and idempotency key must not create a second payment.
2. A provider timeout is an unknown outcome, not proof of failure; never blindly initiate a second charge.
3. Provider callbacks must be authenticated, replay-safe, correlated to the correct provider/payment, and transition-validated.
4. Initiated, provider-confirmed, and settled are different concepts.
5. Ledger entries are append-only; corrections use compensating entries.
6. Every merchant query and mutation is tenant-scoped.
7. Secrets and personal/payment data must never be written to application or infrastructure logs.
8. Live processing remains disabled until provider, legal/regulatory, security, and operational gates are satisfied.

## Immediate engineering priorities

1. Enforce production startup requirements before opening database connections: PostgreSQL, valid Fernet PII key, and complete provider/callback configuration.
2. Add worker heartbeat and queue-age readiness/monitoring; API database readiness alone is insufficient.
3. Run a real Daraja sandbox transaction using the configured application and validate all callback/status-query paths.
4. Complete payment-to-ledger posting and a reliable settlement/receipt reconciliation path.
5. Add outbound merchant webhook delivery and a minimal merchant operations interface.
6. Complete security, privacy, operational, and legal reviews before any live pilot.

## Release discipline

- Keep `main` as the stable release line.
- Develop through small, reviewable pull requests.
- Every milestone must pass Ruff, unit tests, PostgreSQL integration/concurrency tests, migration checks, Docker build/Compose validation, and a documented manual acceptance checklist.
- Do not merge a milestone based only on a green lint job or a sandbox happy path.
