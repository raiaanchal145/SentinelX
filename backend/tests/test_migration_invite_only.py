"""
The invite-only migration (d5e6f7a8b9c0) against a scratch database, so
the real dev/test databases are never touched:

- upgrade head from EMPTY: clean install, enum without 'pending',
  pending_registrations gone.
- upgrade head from POPULATED: a 'pending' organization is converted to
  'active'; rows sitting in pending_registrations (unexpired codes
  included) are discarded by design.
- downgrade base: recreates the empty structures (table + full enum) --
  data is not restored, which is exactly what the migration docstring
  promises.

Alembic is driven programmatically via app.config.settings (env.py
always reads settings.database_url at invocation time, so patching that
attribute retargets every command). Each alembic command runs in a
worker thread: env.py calls asyncio.run(), which cannot execute inside
pytest-asyncio's already-running loop.
"""

import asyncio

import asyncpg
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from alembic.config import Config

from app.config import settings

MIGRATION_HEAD = "d5e6f7a8b9c0"
PREVIOUS_REVISION = "b8c9d0e1f2a3"
SCRATCH_DB = "sentinelx_migration_scratch"


def _alembic_config() -> Config:
    cfg = Config("alembic.ini")
    # env.py overwrites sqlalchemy.url from settings at runtime; patching
    # the attribute (done in the fixture) is what actually retargets it.
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    return cfg


def _scratch_url() -> str:
    root, _, _dbname = settings.database_url.rpartition("/")
    return f"{root}/{SCRATCH_DB}"


async def _recreate_scratch_database():
    """DROP + CREATE the scratch database over an asyncpg connection to
    the maintenance database (CREATE DATABASE cannot run in a
    transaction or on the database itself)."""
    root, _, _dbname = settings.database_url.rpartition("/")
    maintenance_dsn = f"{root}/postgres".replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(maintenance_dsn)
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{SCRATCH_DB}"')
    finally:
        await conn.close()


async def _drop_scratch_database():
    root, _, _dbname = settings.database_url.rpartition("/")
    maintenance_dsn = f"{root}/postgres".replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(maintenance_dsn)
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}" WITH (FORCE)')
    finally:
        await conn.close()


def _enum_labels(rows) -> list[str]:
    return [r[0] for r in rows]


async def test_upgrade_empty_populated_and_downgrade(monkeypatch):
    scratch_url = _scratch_url()

    async def _set_url():
        monkeypatch.setattr(settings, "database_url", scratch_url)

    await _set_url()
    await _recreate_scratch_database()
    try:
        engine = create_async_engine(scratch_url, poolclass=NullPool)

        # ------------------------------------------------------------
        # 1. Empty database -> upgrade head: clean install.
        # ------------------------------------------------------------
        await asyncio.to_thread(command.upgrade, _alembic_config(), "head")

        async with engine.connect() as conn:
            version = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
            assert version == MIGRATION_HEAD

            labels = _enum_labels(
                (
                    await conn.execute(
                        text(
                            "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
                            "WHERE t.typname = 'organization_status' ORDER BY e.enumsortorder"
                        )
                    )
                )
            )
            assert labels == ["active", "suspended", "archived"]

            pending_table = (
                await conn.execute(
                    text("SELECT 1 FROM information_schema.tables WHERE table_name = 'pending_registrations'")
                )
            ).scalar()
            assert pending_table is None

        # ------------------------------------------------------------
        # 2. Downgrade -1 (the spec's own gate): the structures come
        #    back on top of the still-existing schema -- the full four-
        #    value enum and the pending_registrations table (empty; no
        #    data is restored).
        # ------------------------------------------------------------
        await asyncio.to_thread(command.downgrade, _alembic_config(), "-1")

        async with engine.connect() as conn:
            version = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
            assert version == PREVIOUS_REVISION

            labels = _enum_labels(
                (
                    await conn.execute(
                        text(
                            "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
                            "WHERE t.typname = 'organization_status' ORDER BY e.enumsortorder"
                        )
                    )
                )
            )
            assert labels == ["pending", "active", "suspended", "archived"]

            pending_table = (
                await conn.execute(
                    text("SELECT 1 FROM information_schema.tables WHERE table_name = 'pending_registrations'")
                )
            ).scalar()
            assert pending_table == 1

        # ------------------------------------------------------------
        # 3. Populated database -> upgrade head: a pending organization
        #    converts to active, registration attempts are discarded.
        # ------------------------------------------------------------
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO organizations (id, name, status, soc_mode, created_via) "
                    "VALUES (gen_random_uuid(), 'Pending Org', 'pending', 'managed', 'self_signup')"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO pending_registrations (id, name, email, password_hash, role, "
                    "verification_code, verification_code_expires_at) "
                    "VALUES (gen_random_uuid(), 'Ghost Owner', 'ghost@example.com', 'x', 'it_developer', '123456', now())"
                )
            )

        await asyncio.to_thread(command.upgrade, _alembic_config(), "head")

        async with engine.connect() as conn:
            statuses = (await conn.execute(text("SELECT status FROM organizations"))).scalars().all()
            assert statuses == ["active"], "the pending organization must be converted, not dropped"

            pending_table = (
                await conn.execute(
                    text("SELECT 1 FROM information_schema.tables WHERE table_name = 'pending_registrations'")
                )
            ).scalar()
            assert pending_table is None

        await engine.dispose()
    finally:
        await _drop_scratch_database()
