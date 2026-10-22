"""
SentinelX QA Test Suite: Database Schema & Guard Integrity.

Module: DB
Owners: Ansh, Riteka Singh, Aanchal Rai
"""

import pytest
from app.database import Base
from config import validate_test_database_url
from tc import tc


@tc(
    id="DB-01",
    module="Database",
    description="Database schema integrity verification: core SOC tables registered in metadata",
    preconditions="SQLAlchemy models imported",
    steps="Inspect Base.metadata.tables for core SentinelX tables",
    expected="Tables 'organizations', 'users', 'admins', 'alerts', 'tickets', 'events' all present",
    type="automated",
    owner="Ansh",
)
def test_db_01_schema_integrity():
    registered_tables = set(Base.metadata.tables.keys())
    required_tables = {
        "organizations",
        "users",
        "admins",
        "alerts",
        "tickets",
        "security_events",
        "incidents",
        "invitations",
    }
    missing = required_tables - registered_tables
    assert not missing, f"Missing required database tables: {missing}"


@tc(
    id="DB-02",
    module="Database",
    description="Database safety guard strictly refuses hosted and production database connections",
    preconditions="Database safety guard initialized",
    steps="Pass dangerous URLs (Supabase, AWS RDS, Neon, production DBs) to validate_test_database_url",
    expected="RuntimeError raised for each unsafe URL, preventing execution",
    type="automated",
    owner="Riteka Singh",
)
def test_db_02_database_safety_guard():
    dangerous_urls = [
        "postgresql+asyncpg://postgres:secret@db.supabase.co:5432/postgres",
        "postgresql+asyncpg://admin:pass@sentinelx.rds.amazonaws.com:5432/sentinelx_prod",
        "postgresql+asyncpg://user:pass@ep-cool-fog-1234.us-east-2.aws.neon.tech/neondb",
        "postgresql+asyncpg://sentinelx:pass@localhost:5432/sentinelx_production",
        "postgresql+asyncpg://sentinelx:pass@localhost:5432/sentinelx",  # missing 'test'
    ]

    for bad_url in dangerous_urls:
        with pytest.raises(RuntimeError) as exc_info:
            validate_test_database_url(bad_url)
        assert "CRITICAL DB SAFETY ERROR" in str(exc_info.value)
