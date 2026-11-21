from pathlib import Path

import pytest

from fringepay.ledger import EntrySide, Journal, LedgerLine
from fringepay.persistence import Database, PaymentRepository


@pytest.mark.asyncio
async def test_ledger_accounts_and_references_are_tenant_scoped(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'tenant-ledger.db'}")
    await database.create_schema()
    repository = PaymentRepository(database)
    tenant_id, _ = await repository.create_tenant("Ledger Tenant")

    for tenant in ("local", tenant_id):
        await repository.create_ledger_account(
            "cash", "Cash", "KES", EntrySide.DEBIT, tenant_id=tenant
        )
        await repository.create_ledger_account(
            "clearing", "Provider clearing", "KES", EntrySide.CREDIT,
            tenant_id=tenant,
        )

    journal = Journal(
        "tenant-shared-reference",
        "KES",
        "Tenant scoped journal",
        (
            LedgerLine("cash", EntrySide.DEBIT, 2000),
            LedgerLine("clearing", EntrySide.CREDIT, 2000),
        ),
    )
    local_id, local_created = await repository.post_journal(journal, "local")
    tenant_journal_id, tenant_created = await repository.post_journal(
        journal, tenant_id
    )

    assert local_created is True
    assert tenant_created is True
    assert local_id != tenant_journal_id
    assert await repository.account_balance("cash", "local") == 2000
    assert await repository.account_balance("cash", tenant_id) == 2000
    await database.close()
