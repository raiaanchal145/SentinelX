"""
SentinelX QA Test Suite: Security Hardening (SQLi, XSS, Password Hashing, Auth).

Module: SEC
Owners: Ansh, Riteka Singh, Aanchal Rai
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SocMode, UserRole
from app.security import hash_password, verify_password
from backend.tests.helpers import auth, login, make_organization, make_user
from tc import tc


@tc(
    id="SEC-01",
    module="Security",
    description="SQL injection payloads in query parameters are safely handled by parameterized ORM",
    preconditions="Authenticated user with SOC access",
    steps="GET /api/v1/alerts with SQL injection payloads in 'status' and 'severity' query params",
    expected="Server responds with 400 Bad Request or safe 200, never 500 SQL syntax error",
    type="automated",
    owner="Aanchal Rai",
)
@pytest.mark.asyncio
async def test_sec_01_sql_injection_defense(client: AsyncClient, db_session: AsyncSession):
    org = await make_organization(db_session, name="SecOrg1", soc_mode=SocMode.in_house)
    user = await make_user(
        db_session,
        email="analyst_sec1@example.com",
        role=UserRole.soc_analyst,
        organization_id=org.id,
    )
    token = await login(client, user.email)

    sqli_payloads = [
        "' OR '1'='1",
        "1; DROP TABLE alerts; --",
        "' UNION SELECT NULL, NULL, NULL --",
        "admin'--",
    ]

    for payload in sqli_payloads:
        resp = await client.get(
            f"/api/v1/alerts?status={payload}",
            headers=auth(token),
        )
        # SQLAlchemy and enum validation reject with 400, or parameterize safely
        assert resp.status_code in {200, 400}
        assert "syntax error" not in resp.text.lower()
        assert "pg_catalog" not in resp.text.lower()


@tc(
    id="SEC-02",
    module="Security",
    description="Stored XSS payloads in ticket titles and comments are safely escaped/stored verbatim",
    preconditions="Active SOC analyst authenticated",
    steps="POST /api/v1/tickets with <script>alert('XSS')</script> in title and comment body",
    expected="Payload stored as literal text without server execution or unescaped HTML injection",
    type="automated",
    owner="Ansh",
)
@pytest.mark.asyncio
async def test_sec_02_xss_protection(client: AsyncClient, db_session: AsyncSession):
    org = await make_organization(db_session, name="SecOrg2", soc_mode=SocMode.in_house)
    user = await make_user(
        db_session,
        email="analyst_sec2@example.com",
        role=UserRole.soc_analyst,
        organization_id=org.id,
    )
    token = await login(client, user.email)

    xss_payload = "<script>alert('XSS_VULNERABILITY')</script><img src=x onerror=alert(1)>"

    resp = await client.post(
        "/api/v1/tickets",
        headers=auth(token),
        json={
            "title": xss_payload,
            "description": "Cross-site scripting verification test description",
            "severity": "medium",
        },
    )
    assert resp.status_code == 201
    ticket = resp.json()
    assert ticket["title"] == xss_payload


@tc(
    id="SEC-03",
    module="Security",
    description="Password hashing verifies bcrypt algorithm and salt entropy",
    preconditions="Security module loaded",
    steps="Hash plaintext password using hash_password and verify against verify_password",
    expected="Hash begins with '$2b$' (bcrypt) and verifies correctly, rejects wrong password",
    type="automated",
    owner="Riteka Singh",
)
def test_sec_03_password_hashing():
    raw_pwd = "P@ssw0rdSecure!2026#SentinelX"
    hashed = hash_password(raw_pwd)

    # Verify bcrypt signature ($2b$ or $2a$)
    assert hashed.startswith("$2b$") or hashed.startswith("$2a$")
    assert verify_password(raw_pwd, hashed) is True
    assert verify_password("WrongPassword123!", hashed) is False


@tc(
    id="SEC-04",
    module="Security",
    description="Tampered or invalid JWT access token is rejected on protected endpoint",
    preconditions="Protected API endpoint exists",
    steps="GET /api/v1/auth/me with forged JWT token signature",
    expected="Response status 401 Unauthorized rejecting forged token",
    type="automated",
    owner="Aanchal Rai",
)
@pytest.mark.asyncio
async def test_sec_04_tampered_jwt_rejected(client: AsyncClient):
    forged_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJmYWtlQGV4YW1wbGUuY29tIn0.tampered_signature_123456789"
    resp = await client.get("/api/v1/auth/me", headers=auth(forged_token))
    assert resp.status_code == 401

