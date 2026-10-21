"""Consent records and device enrollments (P20).

Adds:
1. `consent_records`:
   - Immutable audit records of granted monitoring categories.
   - Polymorphic account pointer (account_type, account_id) with no FK.
   - Categories granted as JSONB list, consent text version stamp.
   - Revocation metadata (revoked_at, revoked_by_account_type, revoked_by_account_id, revocation_reason).
   - Changing consent creates a NEW record and revokes the old one -- history is never mutated.

2. `device_enrollments`:
   - One-time enrollment token (hashed with SHA-256, 30-min expiry, single use).
   - Device hardware/OS and agent version attributes.
   - Status: pending_consent | enrolled | revoked | expired.
   - Last heartbeat & last seen timestamps.
   - Foreign keys to event_sources (SET NULL), api_keys (SET NULL), and consent_records (SET NULL).

Revision ID: d6e7f8a9b0c1
Revises: c4d5e6f7a8b9
Create Date: 2026-10-21
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d6e7f8a9b0c1"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. consent_records
    # ------------------------------------------------------------------
    op.create_table(
        "consent_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "asset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("account_type", sa.String(10), nullable=False),  # "user" | "admin"
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("categories_granted", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("consent_text_version", sa.String(20), nullable=False),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(300), nullable=True),
        sa.Column(
            "consented_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_account_type", sa.String(10), nullable=True),
        sa.Column("revoked_by_account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("revocation_reason", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_consent_records_org_asset",
        "consent_records",
        ["organization_id", "asset_id"],
    )
    op.create_index(
        "ix_consent_records_asset_revoked",
        "consent_records",
        ["asset_id", "revoked_at"],
    )
    op.create_index(
        "ix_consent_records_account",
        "consent_records",
        ["account_type", "account_id"],
    )

    # ------------------------------------------------------------------
    # 2. device_enrollments
    # ------------------------------------------------------------------
    op.create_table(
        "device_enrollments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "asset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("token_prefix", sa.String(20), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending_consent"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("device_name", sa.String(200), nullable=True),
        sa.Column("operating_system", sa.String(120), nullable=True),
        sa.Column("agent_version", sa.String(50), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "event_source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("event_sources.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "api_key_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("api_keys.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "consent_record_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("consent_records.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("enrolled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_account_type", sa.String(10), nullable=False),
        sa.Column("created_by_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_device_enrollments_org_asset",
        "device_enrollments",
        ["organization_id", "asset_id"],
    )
    op.create_index(
        "ix_device_enrollments_token_hash",
        "device_enrollments",
        ["token_hash"],
    )
    op.create_index(
        "ix_device_enrollments_status",
        "device_enrollments",
        ["status"],
    )
    op.create_index(
        "ix_device_enrollments_api_key_id",
        "device_enrollments",
        ["api_key_id"],
    )
    op.create_index(
        "ix_device_enrollments_last_heartbeat",
        "device_enrollments",
        ["last_heartbeat_at"],
    )


def downgrade() -> None:
    op.drop_table("device_enrollments")
    op.drop_table("consent_records")
