"""Add durable provider dispatch outbox."""

import sqlalchemy as sa

from alembic import op

revision = "0002_provider_outbox"
down_revision = "0001_payment_storage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_dispatch_outbox",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("payment_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["payment_id"], ["payments.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("payment_id"),
    )


def downgrade() -> None:
    op.drop_table("provider_dispatch_outbox")
