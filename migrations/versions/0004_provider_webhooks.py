"""Add provider webhook replay records."""

import sqlalchemy as sa
from alembic import op

revision = "0004_provider_webhooks"
down_revision = "0003_double_entry_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_webhook_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("payment_id", sa.String(length=36), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["payment_id"], ["payments.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("provider", "event_id", name="uq_provider_webhook_event"),
    )


def downgrade() -> None:
    op.drop_table("provider_webhook_events")
