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
            table_names = set(inspect(engine).get_table_names())
        finally:
            engine.dispose()
        expected = {
            "payments",
            "idempotency_keys",
            "provider_dispatch_outbox",
            "ledger_accounts",
            "ledger_transactions",
            "ledger_entries",
            "provider_webhook_events",
            "api_credentials",
            "alembic_version",
        }
        assert expected <= table_names
    finally:
        get_settings.cache_clear()
