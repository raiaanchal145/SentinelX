"""Add last_seen_at to sessions and 2FA columns to admins and users -- P25

Revision ID: f1a2b3c4d5e6
Revises: e8f9a0b1c2d3
Create Date: 2026-10-22 07:45:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "f1a2b3c4d5e6"
down_revision = "e8f9a0b1c2d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. sessions: add last_seen_at
    op.add_column("sessions", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))

    # 2. admins: add two_factor_enabled, two_factor_code, two_factor_code_expires_at
    op.add_column(
        "admins",
        sa.Column("two_factor_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("admins", sa.Column("two_factor_code", sa.String(length=10), nullable=True))
    op.add_column("admins", sa.Column("two_factor_code_expires_at", sa.DateTime(timezone=True), nullable=True))

    # 3. users: add two_factor_enabled, two_factor_code, two_factor_code_expires_at
    op.add_column(
        "users",
        sa.Column("two_factor_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("users", sa.Column("two_factor_code", sa.String(length=10), nullable=True))
    op.add_column("users", sa.Column("two_factor_code_expires_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "two_factor_code_expires_at")
    op.drop_column("users", "two_factor_code")
    op.drop_column("users", "two_factor_enabled")

    op.drop_column("admins", "two_factor_code_expires_at")
    op.drop_column("admins", "two_factor_code")
    op.drop_column("admins", "two_factor_enabled")

    op.drop_column("sessions", "last_seen_at")
