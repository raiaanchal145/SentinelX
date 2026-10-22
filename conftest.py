"""
SentinelX Pytest Configuration, Test Hooks, and Fixtures.

- Enforces strict DB safety: test runs only on TEST_DATABASE_URL.
- Verifies @tc decorator presence and unique TestCaseID formatting.
- Automatically captures test execution results (PASS/FAIL/SKIP/MANUAL).
- Automatically invokes Excel Sync engine at session finish.
- Provides mock email sender capturing codes and invite links without SMTP.
"""

from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys
import time
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# Ensure root and backend are in sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "backend")))

from config import (
    EXCEL_PATH,
    TEST_DATABASE_URL,
    validate_test_database_url,
)
from tc import TestCaseMeta

# 1. Enforce strict DB safety before anything runs
validate_test_database_url(TEST_DATABASE_URL)

# Setup async test DB engine
test_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
TestSessionLocal = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--no-sync",
        action="store_true",
        default=False,
        help="Skip Excel synchronization at the end of the test run.",
    )


def pytest_configure(config: pytest.Config) -> None:
    config._tc_metas: dict[str, TestCaseMeta] = {}
    config._tc_results: dict[str, dict[str, Any]] = {}
    config._session_start_time = time.time()


def pytest_collection_modifyitems(
    session: pytest.Session, config: pytest.Config, items: list[pytest.Item]
) -> None:
    """
    Validates that every test inside tests/ carries a valid @tc decorator
    and that no duplicate TestCaseIDs exist across the entire suite.
    """
    seen_ids: dict[str, tuple[str, str]] = {}  # id -> (nodeid, filepath)
    collected_metas: dict[str, TestCaseMeta] = {}

    for item in items:
        # Check if test has @tc decorator metadata
        meta: TestCaseMeta | None = getattr(item.obj, "__test_case_meta__", None)
        if not meta:
            # Check markers fallback
            marker = item.get_closest_marker("test_case")
            if marker and "meta" in marker.kwargs:
                meta = marker.kwargs["meta"]

        if not meta:
            filepath = item.location[0]
            funcname = item.name
            raise pytest.UsageError(
                f"\n"
                f"====================================================================\n"
                f"LOUD QA RULE ERROR: Missing @tc decorator!\n"
                f"  Test: {funcname}\n"
                f"  File: {filepath}\n"
                f"Every test case must have the @tc decorator specifying ID, Module,\n"
                f"Description, Preconditions, Steps, Expected, Type, and Owner.\n"
                f"===================================================================="
            )

        # Check for duplicate ID
        if meta.id in seen_ids:
            first_node, first_file = seen_ids[meta.id]
            curr_file = item.location[0]
            raise pytest.UsageError(
                f"\n"
                f"====================================================================\n"
                f"LOUD QA RULE ERROR: Duplicate TestCaseID '{meta.id}' detected!\n"
                f"  First defined: {first_file} ({first_node})\n"
                f"  Duplicate in:  {curr_file} ({item.nodeid})\n"
                f"Fix duplicate ID before running tests.\n"
                f"===================================================================="
            )

        seen_ids[meta.id] = (item.nodeid, item.location[0])
        collected_metas[meta.id] = meta

    config._tc_metas = collected_metas


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[Any]):
    """Captures test execution status, duration, and error output per TestCaseID."""
    outcome = yield
    report = outcome.get_result()

    meta: TestCaseMeta | None = getattr(item.obj, "__test_case_meta__", None)
    if not meta:
        return

    # Process on call phase (or on setup phase if setup failed)
    if report.when == "call" or (report.when == "setup" and report.failed):
        tc_id = meta.id
        now_str = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        duration = round(report.duration, 4)

        if meta.type == "manual":
            status = "MANUAL"
            actual_result = "Manual test case - verified manually by tester."
        elif report.passed:
            status = "PASS"
            actual_result = "Verified successfully. Output matches expected result."
        elif report.skipped:
            status = "SKIPPED"
            actual_result = f"Test skipped: {report.longreprtext if report.longreprtext else 'Skipped'}"
        else:
            status = "FAIL"
            # Extract last line or summary of exception
            err_text = str(report.longrepr) if report.longrepr else "Test assertion failed."
            lines = [line.strip() for line in err_text.splitlines() if line.strip()]
            actual_result = lines[-1] if lines else "Test failed."

        item.config._tc_results[tc_id] = {
            "id": tc_id,
            "status": status,
            "actual_result": actual_result,
            "duration": duration,
            "executed_on": now_str,
        }


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Executes Excel synchronization at the end of the pytest run."""
    if session.config.getoption("--no-sync", False):
        return

    # Don't sync if collection failed (e.g. syntax or duplicate ID error)
    if exitstatus == pytest.ExitCode.USAGE_ERROR or exitstatus == pytest.ExitCode.INTERNAL_ERROR:
        return

    collected = getattr(session.config, "_tc_metas", {})
    results = getattr(session.config, "_tc_results", {})

    if not collected:
        return

    # Detect if run was a subset run (-k, -m, or specific test files given)
    args = session.config.args
    has_specific_files = any(arg.endswith(".py") or "::" in arg for arg in args)
    has_keyword = bool(session.config.option.keyword)
    has_marker = bool(session.config.option.markexpr)
    is_subset = has_specific_files or has_keyword or has_marker

    # Get Git commit hash
    git_hash = "unknown"
    try:
        git_res = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if git_res.returncode == 0:
            git_hash = git_res.stdout.strip()
    except Exception:
        pass

    total_duration = round(time.time() - getattr(session.config, "_session_start_time", time.time()), 2)

    try:
        import excel_sync
        excel_sync.sync_test_run(
            collected_metas=collected,
            test_results=results,
            is_subset=is_subset,
            git_hash=git_hash,
            total_duration=total_duration,
        )
    except Exception as exc:
        print(f"\n[EXCEL SYNC ERROR] Failed to sync test results to Excel: {exc}")


# ---------------------------------------------------------
# Test Fixtures: DB, Client, Mock Mailer
# ---------------------------------------------------------

@pytest_asyncio.fixture(scope="session", autouse=True)
async def init_test_schema() -> AsyncGenerator[None, None]:
    """Builds test schema once for the entire session on sentinelx_test."""
    from app.database import Base
    import app.models  # ensure models are loaded

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield

    # Teardown at end of test session
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provides a fresh transactional AsyncSession for each test."""
    async with TestSessionLocal() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Provides an httpx.AsyncClient talking to SentinelX FastAPI app in-process."""
    from app.database import get_db
    from app.main import app

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)


class MockMailer:
    """In-memory email capturer replacing real SMTP during test runs."""

    def __init__(self) -> None:
        self.sent_emails: list[dict[str, Any]] = []

    def record(self, kind: str, to: str, code_or_link: str, **extra: Any) -> None:
        self.sent_emails.append({
            "kind": kind,
            "to": to,
            "value": code_or_link,
            "timestamp": dt.datetime.now(),
            **extra,
        })

    def get_latest_code(self, to_email: str) -> str | None:
        for mail in reversed(self.sent_emails):
            if mail["to"] == to_email and ("code" in mail["kind"] or "verification" in mail["kind"] or "reset" in mail["kind"]):
                return mail["value"]
        return None

    def get_latest_invite_link(self, to_email: str) -> str | None:
        for mail in reversed(self.sent_emails):
            if mail["to"] == to_email and "invite" in mail["kind"]:
                return mail["value"]
        return None

    def clear(self) -> None:
        self.sent_emails.clear()


@pytest.fixture(autouse=True)
def mock_mailer(monkeypatch: pytest.MonkeyPatch) -> MockMailer:
    """Intercepts all email utils so no live SMTP emails are sent and codes are captured."""
    mailer = MockMailer()

    try:
        from app import email_utils

        def _mock_send_verification(to_email: str, name: str, code: str) -> None:
            mailer.record("verification_code", to_email, code, name=name)

        def _mock_send_password_reset(to_email: str, name: str, code: str) -> None:
            mailer.record("password_reset_code", to_email, code, name=name)

        def _mock_send_invitation(to_email: str, org_name: str, role_label: str, link: str, expires_at: Any) -> None:
            mailer.record("invite_link", to_email, link, org_name=org_name, role_label=role_label)

        def _mock_send_2fa(to_email: str, name: str, code: str) -> None:
            mailer.record("two_factor_code", to_email, code, name=name)

        monkeypatch.setattr(email_utils, "send_verification_email", _mock_send_verification)
        monkeypatch.setattr(email_utils, "send_password_reset_email", _mock_send_password_reset)
        monkeypatch.setattr(email_utils, "send_invitation_email", _mock_send_invitation)
        if hasattr(email_utils, "send_two_factor_code_email"):
            monkeypatch.setattr(email_utils, "send_two_factor_code_email", _mock_send_2fa)
    except Exception:
        pass

    return mailer
