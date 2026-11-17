# FringePay

**Provider-independent payment orchestration for African applications.**

FringePay is an API and orchestration layer designed to give applications one consistent interface to multiple authorized payment providers. It owns the integration abstractions, transaction lifecycle, ledger, reconciliation, webhook delivery, and operational controls; external providers remain responsible for executing regulated payment rails.

> **Current status:** Early foundation. No live-money processing is enabled. The first milestone is a tested sandbox engine and provider adapter contract.

## Design principles

- **Provider independence:** application code depends on a stable internal contract, not a provider SDK.
- **Explicit money semantics:** amounts use integer minor units and ISO currency codes; never floating-point arithmetic.
- **Ledger integrity:** immutable, balanced double-entry postings; corrections use compensating entries.
- **Idempotency:** client retries must not create duplicate payment operations.
- **Observable state:** payment transitions are explicit, validated, timestamped, and auditable.
- **Secure by default:** secrets stay outside source control; webhooks are authenticated; sensitive data is minimized.
- **Honest capability boundaries:** sandbox simulations are clearly separated from real provider integrations.

## Planned architecture

```text
Client applications
        |
        v
FringePay API  ---- Authentication / tenant boundary
        |
        v
Payment orchestration
  |        |          |
  v        v          v
Routing  State      Idempotency
         machine
        |
        v
Provider adapter contract
  |          |             |
  v          v             v
Sandbox   Daraja*       Other providers*
        |
        v
Ledger / Reconciliation / Webhook outbox / Audit log

*Provider integrations require approved credentials, contracts, and compliance review.
```

## Initial technology direction

- Python 3.11+
- FastAPI and Pydantic
- PostgreSQL for durable transactional storage
- SQLAlchemy and Alembic for persistence and migrations
- Pytest for unit and integration tests
- Docker Compose for reproducible local development

The implementation may evolve as the repository is audited and tested. Avoid introducing paid infrastructure as a prerequisite for local development.

## Development milestones

1. Repository foundation, domain models, configuration, and CI.
2. Provider interface and deterministic sandbox adapter.
3. Payment API, idempotency, and transaction state machine.
4. Double-entry ledger with balance invariants.
5. Signed webhook delivery and retry/outbox processing.
6. Reconciliation and operational reporting.
7. Daraja adapter in sandbox/test credentials, followed by other authorized providers.
8. Security, compliance, load, and failure-mode hardening before any live-money pilot.

## Safety and scope

FringePay is not a bank, wallet issuer, payment scheme, or substitute for provider authorization. It will not claim to move money independently of regulated/authorized payment rails. Live processing must remain disabled until provider approval, legal/regulatory assessment, security review, and operational controls are in place.

## Local development

Setup instructions will be added with the first runnable API milestone. Never commit credentials, private keys, production customer data, or real payment secrets.

## License

License selection is intentionally pending until the owner confirms the intended distribution and commercial model.
