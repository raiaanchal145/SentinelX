"""
Shared pytest fixtures: an async Postgres test database (separate from
your real dev database) and an httpx client wired to the FastAPI app
through it.

Before running `pytest`, create the test database once:
    createdb sentinelx_test
(or point TEST_DATABASE_URL at any Postgres database you're fine with
these tests creating/dropping every table in -- never your dev database).
"""

import os
from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base, get_db
from app.main import app


def _test_database_url() -> str:
    """
    TEST_DATABASE_URL if set, otherwise DATABASE_URL with the database
    name swapped to "sentinelx_test", so tests never touch the real
    database by accident.
    """
    override = os.environ.get("TEST_DATABASE_URL")
    if override:
        return override
    root, _, _dbname = settings.database_url.rpartition("/")
    return f"{root}/sentinelx_test"


TEST_DATABASE_URL = _test_database_url()
test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSessionLocal = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Fresh schema per test: create every table (and the Postgres enum
    types SQLAlchemy generates for them), yield a session, then drop it
    all. Simple over clever -- a per-test transaction-rollback fixture is
    a fine upgrade later, but create/drop is easy to reason about for a
    first test suite.
    """
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestSessionLocal() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """
    An httpx.AsyncClient that talks to the FastAPI app in-process (no
    real server/port needed), with get_db overridden so every request
    uses the test database session above instead of the real database.
    """

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)
