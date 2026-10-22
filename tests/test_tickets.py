"""
SentinelX QA Test Suite: Ticket Creation, Assignment & Lifecycle.

Module: TKT
Owners: Ansh, Riteka Singh, Aanchal Rai
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SocMode, UserRole
from backend.tests.helpers import auth, login, make_organization, make_user
from tc import tc


@tc(
    id="TKT-01",
    module="Tickets",
    description="Create IT remediation ticket with Critical severity and verify ticket allocation",
    preconditions="Organization in in_house soc_mode with active SOC analyst",
    steps="POST /api/v1/tickets with title, description, and severity='critical'",
    expected="Response status 201 with ticket number allocated and priority set to P1",
    type="automated",
    owner="Ansh",
)
@pytest.mark.asyncio
async def test_tkt_01_create_remediation_ticket(client: AsyncClient, db_session: AsyncSession):
    org = await make_organization(db_session, name="TicketOrg1", soc_mode=SocMode.in_house)
    analyst = await make_user(
        db_session,
        email="analyst_tkt1@example.com",
        role=UserRole.soc_analyst,
        organization_id=org.id,
    )
    token = await login(client, analyst.email)

    payload = {
        "title": "Remediate Critical Ransomware Outbreak on DB Server",
        "description": "Host srv-db-01 showed ransom note artifact and encrypted volume",
        "severity": "critical",
        "priority": "P1",
        "category": "malware",
    }


    resp = await client.post("/api/v1/tickets", headers=auth(token), json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert "ticket_number" in data
    assert data["severity"] == "critical"
    assert data["priority"] in {"P1", "P2"}


@tc(
    id="TKT-02",
    module="Tickets",
    description="Assign ticket to IT developer updates assigned_user_id and status",
    preconditions="Ticket exists in organization",
    steps="POST /api/v1/tickets/{id}/assign with target user_id",
    expected="Response status 200 with ticket assigned_user_id updated",
    type="automated",
    owner="Riteka Singh",
)
@pytest.mark.asyncio
async def test_tkt_02_assign_ticket(client: AsyncClient, db_session: AsyncSession):
    org = await make_organization(db_session, name="TicketOrg2", soc_mode=SocMode.in_house)
    analyst = await make_user(
        db_session,
        email="analyst_tkt2@example.com",
        role=UserRole.soc_analyst,
        organization_id=org.id,
    )
    it_dev = await make_user(
        db_session,
        email="it_dev_tkt2@example.com",
        role=UserRole.it_developer,
        organization_id=org.id,
    )
    token = await login(client, analyst.email)

    # Create ticket
    create_resp = await client.post(
        "/api/v1/tickets",
        headers=auth(token),
        json={"title": "Patch vulnerable log4j service", "severity": "high"},
    )
    assert create_resp.status_code == 201
    ticket_id = create_resp.json()["id"]

    # Assign ticket
    assign_resp = await client.post(
        f"/api/v1/tickets/{ticket_id}/assign",
        headers=auth(token),
        json={"user_id": str(it_dev.id)},
    )
    assert assign_resp.status_code == 200
    assert str(assign_resp.json()["assigned_user_id"]) == str(it_dev.id)


@tc(
    id="TKT-03",
    module="Tickets",
    description="Add comment to ticket record and verify audit trail",
    preconditions="Ticket exists in organization",
    steps="POST /api/v1/tickets/{id}/comments with analyst comment text",
    expected="Response status 201 and comment returned in thread",
    type="automated",
    owner="Aanchal Rai",
)
@pytest.mark.asyncio
async def test_tkt_03_add_ticket_comment(client: AsyncClient, db_session: AsyncSession):
    org = await make_organization(db_session, name="TicketOrg3", soc_mode=SocMode.in_house)
    analyst = await make_user(
        db_session,
        email="analyst_tkt3@example.com",
        role=UserRole.soc_analyst,
        organization_id=org.id,
    )
    token = await login(client, analyst.email)

    # Create ticket
    create_resp = await client.post(
        "/api/v1/tickets",
        headers=auth(token),
        json={"title": "Investigate SSH brute force attempts", "severity": "medium"},
    )
    assert create_resp.status_code == 201
    ticket_id = create_resp.json()["id"]

    # Add comment
    comment_resp = await client.post(
        f"/api/v1/tickets/{ticket_id}/comments",
        headers=auth(token),
        json={"body": "Firewall rule applied to drop offending IP range."},
    )
    assert comment_resp.status_code == 201
    data = comment_resp.json()
    assert "body" in data
    assert "Firewall rule" in data["body"]

