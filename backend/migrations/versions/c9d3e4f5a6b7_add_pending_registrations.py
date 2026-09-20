"""add pending_registrations table

Revision ID: c9d3e4f5a6b7
Revises: b7c1d2e3f4a5
Create Date: 2026-09-20 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'c9d3e4f5a6b7'
down_revision = 'b7c1d2e3f4a5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Registrations live here, unverified, until the OTP is confirmed --
    # no row in `users` exists for them yet. Reuses the existing
    # `user_role` enum type created by the initial migration, so
    # create_type=False (otherwise Postgres errors: type already exists).
    op.create_table(
        'pending_registrations',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column(
            'role',
            postgresql.ENUM(
                'super_admin',
                'organization_admin',
                'soc_analyst',
                'it_developer',
                'auditor',
                name='user_role',
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column('verification_code', sa.String(length=10), nullable=False),
        sa.Column(
            'verification_code_expires_at',
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email'),
    )


def downgrade() -> None:
    op.drop_table('pending_registrations')
