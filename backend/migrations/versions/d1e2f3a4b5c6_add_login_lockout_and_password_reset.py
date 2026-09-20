"""add login lockout counter and password reset fields

Revision ID: d1e2f3a4b5c6
Revises: c9d3e4f5a6b7
Create Date: 2026-09-22 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'd1e2f3a4b5c6'
down_revision = 'c9d3e4f5a6b7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column(
            'failed_login_attempts',
            sa.Integer(),
            nullable=False,
            server_default='0',
        ),
    )
    op.add_column(
        'users',
        sa.Column('password_reset_code', sa.String(length=10), nullable=True),
    )
    op.add_column(
        'users',
        sa.Column(
            'password_reset_code_expires_at',
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column('users', 'password_reset_code_expires_at')
    op.drop_column('users', 'password_reset_code')
    op.drop_column('users', 'failed_login_attempts')
