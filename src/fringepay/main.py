"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from sqlalchemy import text

from fringepay.api import router as payments_router
from fringepay.api import webhook_router
from fringepay.config import get_settings
from fringepay.provider_factory import validate_provider_settings
from fringepay.persistence import (
    LATEST_SCHEMA_REVISION,
    Database,
    PaymentRepository,
)


@asynccontextmanager
async def lifespan(application: FastAPI):
    settings = get_settings()
    validate_provider_settings(settings)
    database = Database(settings.database_url)
    if settings.environment != "production":
        await database.create_schema()
    else:
        await database.verify_schema_revision(LATEST_SCHEMA_REVISION)
    application.state.database = database
    application.state.repository = PaymentRepository(database)
    try:
        yield
    finally:
        await database.close()


settings = get_settings()
app = FastAPI(
    title="FringePay API",
    description="Provider-independent payment orchestration API. Sandbox foundation only.",
    version="0.1.0",
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url=None,
    lifespan=lifespan,
)


@app.get("/health", tags=["operations"])
async def health() -> dict[str, str]:
    """Return process health; this does not imply provider or database readiness."""
    return {"status": "ok", "service": "fringepay"}


@app.get("/ready", tags=["operations"])
async def readiness(request: Request) -> dict[str, str]:
    """Return ready only when the application can reach its configured database."""
    database: Database = request.app.state.database
    try:
        async with database.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="database is not ready") from exc
    return {"status": "ready", "database": "available"}


@app.get(f"{settings.api_prefix}/status", tags=["operations"])
async def api_status() -> dict[str, str]:
    """Expose the current API mode without leaking secrets or infrastructure details."""
    return {
        "service": "fringepay",
        "mode": "sandbox-only",
        "environment": settings.environment,
    }


app.include_router(payments_router, prefix=settings.api_prefix)
app.include_router(webhook_router, prefix=settings.api_prefix)
