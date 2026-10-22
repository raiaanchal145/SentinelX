"""
SentinelX QA Test Automation Configuration & DB Safety Guard.

TEAM:
- Ansh (Team Lead)
- Riteka Singh (QA Engineer)
- Aanchal Rai (QA Engineer)

BIG RULE: STRICT DATABASE SAFETY
- Tests MUST use a dedicated test database (e.g., sentinelx_test).
- NEVER run tests against a shared, staging, or hosted production database.
- Any attempt to use a remote cloud database (AWS, Supabase, Neon, Render, etc.)
  or a database URL without 'test' in the database name will immediately throw
  an unrecoverable RuntimeError to protect live data.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from dotenv import load_dotenv

# Base paths
ROOT_DIR = Path(__file__).resolve().parent
TESTS_DIR = ROOT_DIR / "tests"
DATA_DIR = TESTS_DIR / "data"
EXCEL_PATH = ROOT_DIR / "test_cases.xlsx"
BACKUP_DIR = ROOT_DIR / "backups"
MAX_BACKUPS = 5

# Load environment files: project root first, backend/.env fallback
load_dotenv(ROOT_DIR / ".env")
load_dotenv(ROOT_DIR / "backend" / ".env")

# Patterns matching cloud-hosted or production shared database services
FORBIDDEN_HOSTED_PATTERNS = [
    r"supabase\.co",
    r"rds\.amazonaws\.com",
    r"neon\.tech",
    r"render\.com",
    r"azure\.com",
    r"amazonaws\.com",
    r"cloudsql",
    r"elephantsql\.com",
    r"aivencloud\.com",
    r"railway\.app",
    r"cockroachlabs\.cloud",
]


def validate_test_database_url(url: str | None) -> str:
    """
    Validates that the database URL is safe for test execution.
    Raises RuntimeError if unsafe.
    """
    if not url or not str(url).strip():
        raise RuntimeError(
            "\n"
            "====================================================================\n"
            "CRITICAL DB SAFETY ERROR: TEST_DATABASE_URL is not set!\n"
            "Tests must ONLY run against a local test database.\n"
            "Set TEST_DATABASE_URL in .env (e.g. postgresql+asyncpg://.../sentinelx_test)\n"
            "===================================================================="
        )

    clean_url = str(url).strip()
    url_lower = clean_url.lower()

    # 1. Check for cloud-hosted / production DB signatures
    for pattern in FORBIDDEN_HOSTED_PATTERNS:
        if re.search(pattern, url_lower):
            raise RuntimeError(
                "\n"
                "====================================================================\n"
                "CRITICAL DB SAFETY ERROR: TEST_DATABASE_URL POINTS TO A HOSTED/SHARED DB!\n"
                f"Matched forbidden pattern: {pattern}\n"
                f"Provided URL: {clean_url}\n"
                "TEST EXECUTION REFUSED TO PREVENT PRODUCTION OR SHARED DATA LOSS.\n"
                "===================================================================="
            )

    # 2. Extract database name from path (after last '/' and before '?')
    path_without_params = url_lower.split("?")[0]
    db_name = path_without_params.rpartition("/")[-1]

    if not db_name or "test" not in db_name:
        raise RuntimeError(
            "\n"
            "====================================================================\n"
            f"CRITICAL DB SAFETY ERROR: Database name '{db_name}' DOES NOT contain 'test'!\n"
            f"Provided URL: {clean_url}\n"
            "Tests must ONLY execute against a database specifically named with 'test'\n"
            "(e.g., 'sentinelx_test') to guarantee dev/prod isolation.\n"
            "===================================================================="
        )

    return clean_url


# Determine TEST_DATABASE_URL safely
_raw_test_db_url = os.getenv("TEST_DATABASE_URL")
if not _raw_test_db_url:
    # Build default test DB URL from dev DATABASE_URL if available
    dev_db_url = os.getenv("DATABASE_URL", "postgresql+asyncpg://sentinelx:sentinelx_dev_pw@localhost:5432/sentinelx")
    root_part, _, _ = dev_db_url.rpartition("/")
    _raw_test_db_url = f"{root_part}/sentinelx_test"

TEST_DATABASE_URL = validate_test_database_url(_raw_test_db_url)

# Detection Accuracy Threshold (default 80%)
try:
    DETECTION_ACCURACY_THRESHOLD = float(os.getenv("DETECTION_ACCURACY_THRESHOLD", "0.80"))
except ValueError:
    DETECTION_ACCURACY_THRESHOLD = 0.80

# Sync Delete Mode: "delete" | "archive" | "keep_flagged"
SYNC_DELETE_MODE = os.getenv("SYNC_DELETE_MODE", "delete").lower()
if SYNC_DELETE_MODE not in {"delete", "archive", "keep_flagged"}:
    SYNC_DELETE_MODE = "delete"

# Team Registry
TEAM_MEMBERS = ["Ansh", "Riteka Singh", "Aanchal Rai"]
DEFAULT_OWNER = "Ansh"
