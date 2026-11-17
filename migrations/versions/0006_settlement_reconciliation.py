"""Add tenant-scoped provider settlement reconciliation records."""

import sqlalchemy as sa
from alembic import op

revision = "0006_settlement_reconciliation"
down_revision = "0005_api_credentials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "settlement_records",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("provider_reference", sa.String(length=128), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_reference", sa.String(length=128), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("payment_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "payment_id"],
            ["payments.tenant_id", "payments.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "provider",
            "provider_reference",
            name="uq_settlement_provider_reference",
        ),
    )


def downgrade() -> None:
    op.drop_table("settlement_records")
