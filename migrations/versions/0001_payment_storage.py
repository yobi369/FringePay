"""Create payment and idempotency tables."""

from alembic import op
import sqlalchemy as sa

revision = "0001_payment_storage"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("reference", sa.String(length=128), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("provider_reference", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "idempotency_keys",
        sa.Column("key", sa.String(length=128), primary_key=True),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("payment_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["payment_id"], ["payments.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("payment_id"),
    )


def downgrade() -> None:
    op.drop_table("idempotency_keys")
    op.drop_table("payments")
