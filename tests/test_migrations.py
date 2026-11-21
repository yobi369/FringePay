from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from fringepay.config import get_settings


def test_initial_migration_creates_expected_tables(
    tmp_path: Path, monkeypatch
) -> None:
    database_path = tmp_path / "migration.db"
    monkeypatch.setenv(
        "FRINGEPAY_DATABASE_URL",
        f"sqlite+aiosqlite:///{database_path}",
    )
    get_settings.cache_clear()
    try:
        command.upgrade(Config("alembic.ini"), "head")
        engine = create_engine(f"sqlite:///{database_path}")
        try:
            inspector = inspect(engine)
            table_names = set(inspector.get_table_names())
            payment_columns = {column["name"] for column in inspector.get_columns("payments")}
        finally:
            engine.dispose()
        expected = {
            "tenants",
            "payments",
            "idempotency_keys",
            "provider_dispatch_outbox",
            "ledger_accounts",
            "ledger_transactions",
            "ledger_entries",
            "provider_webhook_events",
            "api_credentials",
            "settlement_records",
            "alembic_version",
        }
        assert expected <= table_names
        assert "phone_number" in payment_columns
    finally:
        get_settings.cache_clear()
