"""Add optional customer phone number for mobile money payment requests."""

import sqlalchemy as sa
from alembic import op

revision = "0007_payment_phone_number"
down_revision = "0006_settlement_reconciliation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("payments", sa.Column("phone_number", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("payments", "phone_number")
