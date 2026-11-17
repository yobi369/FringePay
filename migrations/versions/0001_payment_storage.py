"""Create tenant, payment, and idempotency tables."""

import datetime

import sqlalchemy as sa
from alembic import op

revision = "0001_payment_storage"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    tenants = sa.table(
        "tenants",
        sa.column("id", sa.String()),
        sa.column("name", sa.String()),
        sa.column("status", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        tenants,
        [{
            "id": "local",
            "name": "Local Development",
            "status": "active",
            "created_at": datetime.datetime.now(datetime.UTC),
        }],
    )
    op.create_table(
        "payments",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("reference", sa.String(length=128), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("provider_reference", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "tenant_id", "provider", "provider_reference",
            name="uq_payment_tenant_provider_reference",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_payments_tenant_id"),
    )
    op.create_table(
        "idempotency_keys",
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("payment_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["payment_id"], ["payments.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("tenant_id", "key"),
        sa.UniqueConstraint("payment_id"),
    )


def downgrade() -> None:
    op.drop_table("idempotency_keys")
    op.drop_table("payments")
    op.drop_table("tenants")
