"""add email verification fields

Revision ID: b7c1d2e3f4a5
Revises: e0f6e7bfc5a3
Create Date: 2026-09-10 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7c1d2e3f4a5'
down_revision = 'e0f6e7bfc5a3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column(
            'is_verified',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        'users',
        sa.Column('verification_code', sa.String(length=10), nullable=True),
    )
    op.add_column(
        'users',
        sa.Column(
            'verification_code_expires_at',
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column('users', 'verification_code_expires_at')
    op.drop_column('users', 'verification_code')
    op.drop_column('users', 'is_verified')
