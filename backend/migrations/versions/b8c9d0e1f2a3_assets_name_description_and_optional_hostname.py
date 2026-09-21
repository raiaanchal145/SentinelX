"""assets: add name/description, make hostname optional, unique hostname per org

Revision ID: b8c9d0e1f2a3
Revises: a4b5c6d7e8f9
Create Date: 2026-09-21 00:00:00.000000

Adds the two columns the real Assets API needs that the original
assets table never had (`name`, `description`), and loosens `hostname`
from NOT NULL to nullable -- some asset types (an "application" or a
"cloud_resource", say) may not have one. Existing rows get `name`
backfilled from `hostname` (or a placeholder if that's also empty)
before `name` is made NOT NULL, the same backfill-then-constrain
pattern used elsewhere in this schema for a column that has to become
required under existing data.

Also adds a partial unique index on (organization_id, lower(hostname))
that only applies WHERE hostname IS NOT NULL, so two assets with no
hostname never collide but two with the same hostname in one
organization do -- enforced at the database level, not just in the
API's duplicate check.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b8c9d0e1f2a3'
down_revision = 'a4b5c6d7e8f9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('assets', sa.Column('name', sa.String(length=200), nullable=True))
    op.add_column('assets', sa.Column('description', sa.Text(), nullable=True))

    # Backfill before constraining -- any pre-existing row gets its
    # hostname as its name, or a placeholder if it somehow has neither.
    op.execute("UPDATE assets SET name = hostname WHERE name IS NULL AND hostname IS NOT NULL")
    op.execute("UPDATE assets SET name = 'Unnamed asset' WHERE name IS NULL")

    op.alter_column('assets', 'name', existing_type=sa.String(length=200), nullable=False)
    op.alter_column('assets', 'hostname', existing_type=sa.String(length=200), nullable=True)

    op.create_index(
        'uq_assets_org_lower_hostname',
        'assets',
        ['organization_id', sa.text('lower(hostname)')],
        unique=True,
        postgresql_where=sa.text('hostname IS NOT NULL'),
    )


def downgrade() -> None:
    op.drop_index('uq_assets_org_lower_hostname', table_name='assets')

    # Any asset left with no hostname would violate the restored NOT
    # NULL constraint -- give it back a synthetic one rather than fail
    # the downgrade outright.
    op.execute("UPDATE assets SET hostname = 'unknown-' || id::text WHERE hostname IS NULL")
    op.alter_column('assets', 'hostname', existing_type=sa.String(length=200), nullable=False)

    op.drop_column('assets', 'description')
    op.drop_column('assets', 'name')
