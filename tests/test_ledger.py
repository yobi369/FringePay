from pathlib import Path

import pytest

from fringepay.ledger import EntrySide, Journal, LedgerLine
from fringepay.persistence import Database, PaymentRepository


@pytest.mark.asyncio
async def test_balanced_journal_posts_once_and_derives_balances(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'ledger.db'}")
    await database.create_schema()
    repository = PaymentRepository(database)
    await repository.create_ledger_account(
        "cash_kes", "Cash clearing", "KES", EntrySide.DEBIT
    )
    await repository.create_ledger_account(
        "provider_payable_kes", "Provider payable", "KES", EntrySide.CREDIT
    )
    journal = Journal(
        reference="settlement-001",
        currency="KES",
        description="Sandbox settlement example",
        lines=(
            LedgerLine("cash_kes", EntrySide.DEBIT, 1250),
            LedgerLine("provider_payable_kes", EntrySide.CREDIT, 1250),
        ),
    )

    transaction_id, created = await repository.post_journal(journal)
    replay_id, replay_created = await repository.post_journal(journal)

    assert created is True
    assert replay_created is False
    assert replay_id == transaction_id
    assert await repository.account_balance("cash_kes") == 1250
    assert await repository.account_balance("provider_payable_kes") == 1250
    await database.close()


def test_journal_rejects_unbalanced_entries() -> None:
    with pytest.raises(ValueError, match="debits must equal credits"):
        Journal(
            reference="unbalanced-001",
            currency="KES",
            description="Invalid journal",
            lines=(
                LedgerLine("cash_kes", EntrySide.DEBIT, 1000),
                LedgerLine("provider_payable_kes", EntrySide.CREDIT, 900),
            ),
        )


@pytest.mark.asyncio
async def test_journal_rejects_reference_reuse_with_changed_entries(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'ledger-conflict.db'}")
    await database.create_schema()
    repository = PaymentRepository(database)
    await repository.create_ledger_account(
        "cash_kes", "Cash clearing", "KES", EntrySide.DEBIT
    )
    await repository.create_ledger_account(
        "provider_payable_kes", "Provider payable", "KES", EntrySide.CREDIT
    )
    original = Journal(
        "journal-same-ref",
        "KES",
        "Original",
        (
            LedgerLine("cash_kes", EntrySide.DEBIT, 500),
            LedgerLine("provider_payable_kes", EntrySide.CREDIT, 500),
        ),
    )
    changed = Journal(
        "journal-same-ref",
        "KES",
        "Changed",
        (
            LedgerLine("cash_kes", EntrySide.DEBIT, 600),
            LedgerLine("provider_payable_kes", EntrySide.CREDIT, 600),
        ),
    )
    await repository.post_journal(original)
    with pytest.raises(ValueError, match="different entries"):
        await repository.post_journal(changed)
    await database.close()


@pytest.mark.asyncio
async def test_journal_requires_accounts_in_the_same_currency(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'ledger-currency.db'}")
    await database.create_schema()
    repository = PaymentRepository(database)
    await repository.create_ledger_account(
        "cash_kes", "Cash clearing", "KES", EntrySide.DEBIT
    )
    await repository.create_ledger_account(
        "provider_payable_usd", "Provider payable", "USD", EntrySide.CREDIT
    )
    journal = Journal(
        "mixed-currency-ref",
        "KES",
        "Invalid currency mix",
        (
            LedgerLine("cash_kes", EntrySide.DEBIT, 100),
            LedgerLine("provider_payable_usd", EntrySide.CREDIT, 100),
        ),
    )
    with pytest.raises(ValueError, match="currency mismatch"):
        await repository.post_journal(journal)
    await database.close()
