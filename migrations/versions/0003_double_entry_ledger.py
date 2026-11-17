"""Create double-entry ledger tables."""

import sqlalchemy as sa

from alembic import op

revision = "0003_double_entry_ledger"
down_revision = "0002_provider_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ledger_accounts",
        sa.Column("code", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("normal_side", sa.String(length=6), nullable=False),
    )
    op.create_table(
        "ledger_transactions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("reference", sa.String(length=128), nullable=False, unique=True),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("description", sa.String(length=256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "ledger_entries",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("transaction_id", sa.String(length=36), nullable=False),
        sa.Column("account_code", sa.String(length=64), nullable=False),
        sa.Column("side", sa.String(length=6), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["transaction_id"], ["ledger_transactions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["account_code"], ["ledger_accounts.code"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("transaction_id", "account_code"),
    )


def downgrade() -> None:
    op.drop_table("ledger_entries")
    op.drop_table("ledger_transactions")
    op.drop_table("ledger_accounts")
