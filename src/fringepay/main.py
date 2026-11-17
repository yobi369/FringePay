"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from fringepay.api import router as payments_router
from fringepay.config import get_settings
from fringepay.persistence import Database, PaymentRepository


@asynccontextmanager
async def lifespan(application: FastAPI):
    settings = get_settings()
    if settings.environment == "production" and not settings.api_key:
        raise RuntimeError("FRINGEPAY_API_KEY must be configured in production")
    database = Database(settings.database_url)
    if settings.environment != "production":
        await database.create_schema()
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


@app.get(f"{settings.api_prefix}/status", tags=["operations"])
async def api_status() -> dict[str, str]:
    """Expose the current API mode without leaking secrets or infrastructure details."""
    return {
        "service": "fringepay",
        "mode": "sandbox-only",
        "environment": settings.environment,
    }


app.include_router(payments_router, prefix=settings.api_prefix)
