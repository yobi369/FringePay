import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from fringepay.config import get_settings
from fringepay.domain import Money
from fringepay.main import app
from fringepay.persistence import Database, PaymentRepository
from fringepay.service import CreatePayment


def test_payment_api_enforces_tenant_isolation(
    tmp_path: Path, monkeypatch
) -> None:
    database_path = tmp_path / "tenant-api.db"
    database_url = f"sqlite+aiosqlite:///{database_path}"
    monkeypatch.setenv("FRINGEPAY_DATABASE_URL", database_url)
    get_settings.cache_clear()

    async def seed_tenant_payment() -> tuple[str, str, str]:
        database = Database(database_url)
        await database.create_schema()
        repository = PaymentRepository(database)
        tenant_id, api_key = await repository.create_tenant("Tenant API Test")
        payment, _ = await repository.reserve(
            CreatePayment(Money(1100, "KES"), "isolated-order"),
            "tenant-isolated-idempotency",
            tenant_id=tenant_id,
        )
        await database.close()
        return tenant_id, api_key, payment.id

    try:
        _, tenant_key, payment_id = asyncio.run(seed_tenant_payment())
        with TestClient(app) as client:
            local_response = client.get(
                f"/v1/payments/{payment_id}",
                headers={"X-API-Key": "local-development-key"},
            )
            tenant_response = client.get(
                f"/v1/payments/{payment_id}",
                headers={"X-API-Key": tenant_key},
            )

        assert local_response.status_code == 404
        assert tenant_response.status_code == 200
        assert tenant_response.json()["id"] == payment_id
    finally:
        get_settings.cache_clear()
