"""FastAPI application entry point."""

from fastapi import FastAPI

from fringepay.config import get_settings

settings = get_settings()
app = FastAPI(
    title="FringePay API",
    description="Provider-independent payment orchestration API. Sandbox foundation only.",
    version="0.1.0",
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url=None,
)


@app.get("/health", tags=["operations"])
async def health() -> dict[str, str]:
    """Return process health; this does not imply provider or database readiness."""
    return {"status": "ok", "service": "fringepay"}


@app.get(f"{settings.api_prefix}/status", tags=["operations"])
async def api_status() -> dict[str, str]:
    """Expose the current API mode without leaking secrets or infrastructure details."""
    return {"service": "fringepay", "mode": "sandbox-only", "environment": settings.environment}

from fringepay.api import router as payments_router

app.include_router(payments_router, prefix=settings.api_prefix)
