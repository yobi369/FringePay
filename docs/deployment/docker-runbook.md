# Container deployment runbook

## Local API + worker + PostgreSQL

The Compose stack starts three services: PostgreSQL, the FastAPI service, and the durable outbox worker.

    cp .env.example .env
    docker compose up --build -d
    docker compose ps
    curl http://localhost:8000/health
    curl http://localhost:8000/ready

View logs:

    docker compose logs -f api worker

Stop the stack:

    docker compose down

Keep the named PostgreSQL volume when stopping the stack. To intentionally delete local data, use docker compose down -v.

## Database migrations

Fresh local development uses SQLAlchemy metadata creation. Before a shared or production deployment, run the versioned Alembic migrations exactly once:

    docker compose run --rm --no-deps api alembic upgrade head

The production API verifies the database revision at startup and refuses to serve traffic when the schema is behind.

## Daraja sandbox

Set the Daraja sandbox credentials, callback URL/token, and PII encryption key in the environment used by both API and worker. Never put secrets in the repository or container image.

Set:

    FRINGEPAY_ENVIRONMENT=development
    FRINGEPAY_DEFAULT_PROVIDER=daraja
    FRINGEPAY_DARAJA_ENVIRONMENT=sandbox
    FRINGEPAY_DARAJA_CONSUMER_KEY=...
    FRINGEPAY_DARAJA_CONSUMER_SECRET=...
    FRINGEPAY_DARAJA_SHORTCODE=...
    FRINGEPAY_DARAJA_PASSKEY=...
    FRINGEPAY_DARAJA_CALLBACK_URL=https://public-host/v1/webhooks/daraja?token=<same-callback-secret>
    FRINGEPAY_DARAJA_CALLBACK_SECRET=<high-entropy-secret>
    FRINGEPAY_PII_ENCRYPTION_KEY=<fernet-key>

The callback endpoint must be reachable over HTTPS. Redact its query string from proxy/access logs. The same database, provider credentials, callback settings, and encryption key must be available to the API and worker.

## Production deployment requirements

Do not use the local Compose password or development defaults in production.

1. Use a managed PostgreSQL database with automated backups and point-in-time recovery.
2. Deploy the API and worker as separate, always-on services using the same immutable image version.
3. Set FRINGEPAY_ENVIRONMENT=production and FRINGEPAY_DEFAULT_PROVIDER=daraja only after the provider sandbox has been tested.
4. Configure a strong database password, Daraja credentials, a callback secret of at least 32 characters, and a valid Fernet key through the hosting provider's secret manager.
5. Run alembic upgrade head as a release/pre-deploy step before starting the new API and worker.
6. Configure the platform health check to GET /ready. GET /health is process health only.
7. Configure TLS, request/body limits, rate limiting, access-log redaction, monitoring, alerting, backup restore tests, and an incident-response contact.
8. Keep live Daraja endpoints disabled. This release rejects any Daraja environment other than sandbox.
9. Obtain written provider approval and Kenyan legal/regulatory advice on whether the actual orchestration, processing, custody, and data flows require CBK authorisation or other approvals before commercial live processing.

A sleeping/free web service or an intermittently available worker is not suitable for handling real payment traffic. Use free hosting only for demos and controlled sandbox testing, not as a production availability commitment.

## Rollback

- Roll back API and worker to the same previous image version.
- Do not downgrade the database automatically during application rollback.
- Preserve unknown-outcome payments and outbox records for investigation; never replay them blindly.
- Verify the API readiness endpoint and worker logs after rollback.
