"""Add tenant-scoped API credentials."""

import datetime
import hashlib

import sqlalchemy as sa
from alembic import op

revision = "0005_api_credentials"
down_revision = "0004_provider_webhooks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_credentials",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("key_prefix", sa.String(length=24), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="RESTRICT"
        ),
    )
    op.create_index(
        "ix_api_credentials_key_prefix",
        "api_credentials",
        ["key_prefix"],
    )
    credentials = sa.table(
        "api_credentials",
        sa.column("id", sa.String()),
        sa.column("tenant_id", sa.String()),
        sa.column("key_prefix", sa.String()),
        sa.column("key_hash", sa.String()),
        sa.column("label", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        credentials,
        [{
            "id": "local-development-credential",
            "tenant_id": "local",
            "key_prefix": "local-development-key",
            "key_hash": hashlib.sha256(b"local-development-key").hexdigest(),
            "label": "Local development key",
            "created_at": datetime.datetime.now(datetime.UTC),
        }],
    )


def downgrade() -> None:
    op.drop_index("ix_api_credentials_key_prefix", table_name="api_credentials")
    op.drop_table("api_credentials")
