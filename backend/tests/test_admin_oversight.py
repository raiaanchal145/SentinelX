"""
Tests for Admin Oversight Dashboards & Reassignments (P22).
Verifies:
- Aggregate counts match hand count from seeded data
- super_admin only for platform overview
- platform_soc_analyst isolated to assigned managed orgs & own workload
- Reassign alerts & incidents with mandatory reason and audit entry
- Reassign rules enforcing assigned platform SOC analysts only
"""

from datetime import datetime, timedelta, timezone
import uuid

import pytest
from sqlalchemy import select

from app.models import (
    AdminLevel,
    Agent,
    AgentRun,
    AgentType,
    Alert,
    AlertHistory,
    AlertStatus,
    Asset,
    AuditLog,
    DeviceEnrollment,
    EventSeverity,
    Incident,
    IncidentStatus,
    IncidentTimeline,
    OrganizationStatus,
    SecurityEvent,
    SocMode,
    SocOrganizationAssignment,
    Team,
    Ticket,
    TicketStatus,
    UserRole,
)
from tests.helpers import auth, login, make_admin, make_organization, make_team, make_user

BASE_OVERVIEW = "/api/v1/admin/oversight/overview"
BASE_SOC = "/api/v1/admin/oversight/soc"
BASE_IT = "/api/v1/admin/oversight/it"


async def _super_admin_token(client, db_session, email="super@example.com"):
    await make_admin(db_session, email=email, admin_level=AdminLevel.super_admin)
    return await login(client, email)


async def test_oversight_access_roles(client, db_session):
    org = await make_organization(db_session, name="Org Alpha")
    super_tok = await _super_admin_token(client, db_session)

    soc_admin = await make_admin(
        db_session, email="soc@example.com", admin_level=AdminLevel.platform_soc_analyst
    )
    soc_tok = await login(client, soc_admin.email)

    owner = await make_admin(
        db_session, email="owner@example.com", organization_id=org.id, admin_level=AdminLevel.organization_admin
    )
    owner_tok = await login(client, owner.email)

    user = await make_user(db_session, email="user@example.com", organization_id=org.id)
    user_tok = await login(client, user.email)

    # 1. Overview is super_admin only
    assert (await client.get(BASE_OVERVIEW, headers=auth(super_tok))).status_code == 200
    assert (await client.get(BASE_OVERVIEW, headers=auth(soc_tok))).status_code == 403
    assert (await client.get(BASE_OVERVIEW, headers=auth(owner_tok))).status_code == 403
    assert (await client.get(BASE_OVERVIEW, headers=auth(user_tok))).status_code == 403

    # 2. SOC oversight is platform admins only (super_admin + platform_soc_analyst)
    assert (await client.get(BASE_SOC, headers=auth(super_tok))).status_code == 200
    assert (await client.get(BASE_SOC, headers=auth(soc_tok))).status_code == 200
    assert (await client.get(BASE_SOC, headers=auth(owner_tok))).status_code == 403
    assert (await client.get(BASE_SOC, headers=auth(user_tok))).status_code == 403

    # 3. IT oversight is platform admins only
    assert (await client.get(BASE_IT, headers=auth(super_tok))).status_code == 200
    assert (await client.get(BASE_IT, headers=auth(soc_tok))).status_code == 200
    assert (await client.get(BASE_IT, headers=auth(owner_tok))).status_code == 403
    assert (await client.get(BASE_IT, headers=auth(user_tok))).status_code == 403


async def test_overview_aggregates_match_seeded_data(client, db_session):
    super_tok = await _super_admin_token(client, db_session)

    # 2 orgs: 1 active managed, 1 suspended in_house
    org1 = await make_organization(db_session, name="Org Managed", status=OrganizationStatus.active, soc_mode=SocMode.managed)
    org2 = await make_organization(db_session, name="Org InHouse", status=OrganizationStatus.suspended, soc_mode=SocMode.in_house)

    # 2 assets
    asset1 = Asset(organization_id=org1.id, name="Server A", hostname="srv-a.corp", asset_type="server", status="active")
    asset2 = Asset(organization_id=org2.id, name="Server B", hostname="srv-b.corp", asset_type="server", status="retired")
    db_session.add_all([asset1, asset2])
    await db_session.flush()

    # 2 devices: 1 connected, 1 offline
    now = datetime.now(timezone.utc)
    dev1 = DeviceEnrollment(
        organization_id=org1.id,
        asset_id=asset1.id,
        token_hash="hash1",
        token_prefix="sxe_1",
        status="enrolled",
        expires_at=now + timedelta(days=1),
        created_by_account_type="admin",
        created_by_account_id=uuid.uuid4(),
        last_heartbeat_at=now - timedelta(seconds=30),  # connected (< 2m)
    )
    dev2 = DeviceEnrollment(
        organization_id=org1.id,
        asset_id=asset1.id,
        token_hash="hash2",
        token_prefix="sxe_2",
        status="enrolled",
        expires_at=now + timedelta(days=1),
        created_by_account_type="admin",
        created_by_account_id=uuid.uuid4(),
        last_heartbeat_at=now - timedelta(minutes=15),  # offline (> 10m)
    )
    db_session.add_all([dev1, dev2])

    # 2 incidents: 1 critical open, 1 high resolved
    inc1 = Incident(
        organization_id=org1.id,
        title="Active Ransomware",
        severity=EventSeverity.critical,
        status=IncidentStatus.investigating,
    )
    inc2 = Incident(
        organization_id=org1.id,
        title="Old Phish",
        severity=EventSeverity.high,
        status=IncidentStatus.resolved,
    )
    db_session.add_all([inc1, inc2])

    # AI agent & run
    agent = Agent(name="TriageAgent", agent_type=AgentType.triage, model="gemini-1.5-pro")
    db_session.add(agent)
    await db_session.flush()

    run1 = AgentRun(
        organization_id=org1.id,
        agent_id=agent.id,
        target_type="incident",
        status="succeeded",
        tokens_used=1250,
        cost_usd=0.0125,
    )
    db_session.add(run1)
    await db_session.commit()

    resp = await client.get(BASE_OVERVIEW, headers=auth(super_tok))
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # Hand-counts
    assert data["organizations"]["total"] == 2
    assert data["organizations"]["by_status"]["active"] == 1
    assert data["organizations"]["by_status"]["suspended"] == 1
    assert data["organizations"]["by_mode"]["managed"] == 1
    assert data["organizations"]["by_mode"]["in_house"] == 1

    assert data["devices"]["connected"] == 1
    assert data["devices"]["offline"] == 1
    assert data["devices"]["total"] == 2

    assert data["stats"]["assets"] == 1  # 1 active, 1 retired excluded
    assert data["stats"]["open_incidents"] == 1
    assert data["stats"]["incidents_by_severity"]["critical"] == 1
    assert data["stats"]["incidents_by_severity"]["high"] == 0  # inc2 was resolved!

    assert data["ai_usage"]["total_runs"] == 1
    assert data["ai_usage"]["tokens_used"] == 1250
    assert data["ai_usage"]["cost_usd"] == 0.0125


async def test_soc_oversight_and_analyst_isolation(client, db_session):
    super_tok = await _super_admin_token(client, db_session)

    org_assigned = await make_organization(db_session, name="Assigned Org", soc_mode=SocMode.managed)
    org_unassigned = await make_organization(db_session, name="Unassigned Org", soc_mode=SocMode.managed)

    analyst = await make_admin(
        db_session, email="analyst1@example.com", name="Bob Analyst", admin_level=AdminLevel.platform_soc_analyst
    )
    analyst_tok = await login(client, analyst.email)

    # Assign analyst to org_assigned only
    db_session.add(SocOrganizationAssignment(organization_id=org_assigned.id, admin_id=analyst.id))

    # Add open alert to org_assigned and assign to analyst
    now = datetime.now(timezone.utc)
    alert1 = Alert(
        organization_id=org_assigned.id,
        title="Brute Force",
        rule_name="Brute Force Login",
        severity=EventSeverity.high,
        status=AlertStatus.new,
        first_seen_at=now,
        last_seen_at=now,
        assigned_account_type="admin",
        assigned_account_id=analyst.id,
    )
    # Add unassigned alert to org_unassigned
    alert2 = Alert(
        organization_id=org_unassigned.id,
        title="Port Scan",
        rule_name="Network Port Scan",
        severity=EventSeverity.medium,
        status=AlertStatus.new,
        first_seen_at=now,
        last_seen_at=now,
    )
    db_session.add_all([alert1, alert2])
    await db_session.commit()

    # 1. super_admin view: sees both orgs, coverage gap for unassigned org, workload for analyst
    resp_super = await client.get(BASE_SOC, headers=auth(super_tok))
    assert resp_super.status_code == 200
    data_super = resp_super.json()

    assert len(data_super["organizations"]) == 2
    # Coverage gap should name "Unassigned Org"
    assert len(data_super["coverage_gaps"]) == 1
    assert data_super["coverage_gaps"][0]["id"] == str(org_unassigned.id)
    # Analyst workload
    assert len(data_super["analyst_workload"]) == 1
    assert data_super["analyst_workload"][0]["open_alerts"] == 1

    # 2. platform_soc_analyst view: isolated to assigned org only
    resp_analyst = await client.get(BASE_SOC, headers=auth(soc_tok := analyst_tok))
    assert resp_analyst.status_code == 200
    data_analyst = resp_analyst.json()

    assert len(data_analyst["organizations"]) == 1
    assert data_analyst["organizations"][0]["id"] == str(org_assigned.id)
    assert len(data_analyst["coverage_gaps"]) == 0  # isolated, no gap management
    assert len(data_analyst["analyst_workload"]) == 1
    assert data_analyst["analyst_workload"][0]["id"] == str(analyst.id)


async def test_it_oversight_aggregates(client, db_session):
    super_tok = await _super_admin_token(client, db_session)
    org = await make_organization(db_session, name="Acme IT Corp")

    team = await make_team(db_session, organization_id=org.id, name="Helpdesk")
    it_dev = await make_user(
        db_session,
        email="dev1@example.com",
        name="Alice Dev",
        role=UserRole.it_developer,
        organization_id=org.id,
        team_id=team.id,
    )

    now = datetime.now(timezone.utc)
    # Ticket P1 overdue
    t1 = Ticket(
        organization_id=org.id,
        ticket_number="TICK-101",
        title="Database Down",
        severity=EventSeverity.critical,
        priority="P1",
        status=TicketStatus.investigating,
        assigned_team_id=team.id,
        assigned_user_id=it_dev.id,
        sla_breached=True,
        resolve_due_at=now - timedelta(hours=1),
    )
    # Ticket P2 at-risk
    t2 = Ticket(
        organization_id=org.id,
        ticket_number="TICK-102",
        title="VPN Slow",
        severity=EventSeverity.high,
        priority="P2",
        status=TicketStatus.assigned,
        assigned_team_id=team.id,
        sla_at_risk=True,
        resolve_due_at=now + timedelta(minutes=30),
    )
    db_session.add_all([t1, t2])
    await db_session.commit()

    resp = await client.get(BASE_IT, headers=auth(super_tok))
    assert resp.status_code == 200
    data = resp.json()

    org_stat = data["organizations"][0]
    assert org_stat["open_tickets_by_priority"]["P1"] == 1
    assert org_stat["open_tickets_by_priority"]["P2"] == 1
    assert org_stat["sla_breached"] == 1
    assert org_stat["sla_at_risk"] == 1

    # Team workload
    team_stat = next(t for t in data["byTeam"] if t["team"]["id"] == str(team.id))
    assert team_stat["open"] == 2
    assert team_stat["overdue"] == 1

    # Workload
    dev_stat = next(w for w in data["workload"] if w["user"]["id"] == str(it_dev.id))
    assert dev_stat["openTasks"] == 1
    assert dev_stat["overdue"] == 1


async def test_reassign_alert_rules_and_audit(client, db_session):
    super_tok = await _super_admin_token(client, db_session)
    org = await make_organization(db_session, name="Secured Corp", soc_mode=SocMode.managed)

    analyst_assigned = await make_admin(
        db_session, email="analyst_assigned@example.com", name="Assigned Analyst", admin_level=AdminLevel.platform_soc_analyst
    )
    analyst_unassigned = await make_admin(
        db_session, email="analyst_unassigned@example.com", name="Unassigned Analyst", admin_level=AdminLevel.platform_soc_analyst
    )

    db_session.add(SocOrganizationAssignment(organization_id=org.id, admin_id=analyst_assigned.id))

    now = datetime.now(timezone.utc)
    alert = Alert(
        organization_id=org.id,
        title="Suspicious Login",
        severity=EventSeverity.medium,
        status=AlertStatus.new,
        first_seen_at=now,
        last_seen_at=now,
    )
    db_session.add(alert)
    await db_session.commit()

    url = f"/api/v1/admin/alerts/{alert.id}/reassign"

    # 1. Rejection: empty reason
    resp_empty = await client.post(
        url,
        json={"analyst_id": str(analyst_assigned.id), "reason": "   "},
        headers=auth(super_tok),
    )
    assert resp_empty.status_code == 400

    # 2. Rejection: analyst not assigned to that org
    resp_unassigned = await client.post(
        url,
        json={"analyst_id": str(analyst_unassigned.id), "reason": "Handover"},
        headers=auth(super_tok),
    )
    assert resp_unassigned.status_code == 422
    assert resp_unassigned.json()["detail"]["code"] == "assignee_not_in_scope"

    # 3. Success: assigned analyst with reason
    resp_ok = await client.post(
        url,
        json={"analyst_id": str(analyst_assigned.id), "reason": "Shift handover to Bob"},
        headers=auth(super_tok),
    )
    assert resp_ok.status_code == 200, resp_ok.text
    body = resp_ok.json()
    assert body["assigned_account_id"] == str(analyst_assigned.id)
    assert body["assigned_account_type"] == "admin"

    # Verify AlertHistory row
    history = (
        await db_session.execute(
            select(AlertHistory).where(AlertHistory.alert_id == alert.id, AlertHistory.action == "reassign")
        )
    ).scalar_one()
    assert history.detail["reason"] == "Shift handover to Bob"
    assert history.detail["assigned_to"] == str(analyst_assigned.id)

    # Verify AuditLog row
    audit = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.target_id == alert.id, AuditLog.action == "alert.reassign")
        )
    ).scalar_one()
    assert audit.details["after"]["reason"] == "Shift handover to Bob"


async def test_reassign_incident_rules_and_audit(client, db_session):
    super_tok = await _super_admin_token(client, db_session)
    org = await make_organization(db_session, name="Incident Corp", soc_mode=SocMode.managed)

    analyst_assigned = await make_admin(
        db_session, email="inc_analyst_assigned@example.com", name="Incident Analyst", admin_level=AdminLevel.platform_soc_analyst
    )
    analyst_unassigned = await make_admin(
        db_session, email="inc_analyst_unassigned@example.com", name="Other Analyst", admin_level=AdminLevel.platform_soc_analyst
    )

    db_session.add(SocOrganizationAssignment(organization_id=org.id, admin_id=analyst_assigned.id))

    inc = Incident(
        organization_id=org.id,
        title="Data Breach Investigation",
        severity=EventSeverity.critical,
        status=IncidentStatus.investigating,
    )
    db_session.add(inc)
    await db_session.commit()

    url = f"/api/v1/admin/incidents/{inc.id}/reassign"

    # 1. Rejection: analyst not assigned to that org
    resp_unassigned = await client.post(
        url,
        json={"analyst_id": str(analyst_unassigned.id), "reason": "Workload balance"},
        headers=auth(super_tok),
    )
    assert resp_unassigned.status_code == 422
    assert resp_unassigned.json()["detail"]["code"] == "assignee_not_in_scope"

    # 2. Success: assigned analyst with reason
    resp_ok = await client.post(
        url,
        json={"analyst_id": str(analyst_assigned.id), "reason": "Escalated for senior review"},
        headers=auth(super_tok),
    )
    assert resp_ok.status_code == 200, resp_ok.text
    body = resp_ok.json()
    assert body["assigned_account_id"] == str(analyst_assigned.id)

    # Verify IncidentTimeline row
    timeline = (
        await db_session.execute(
            select(IncidentTimeline).where(IncidentTimeline.incident_id == inc.id, IncidentTimeline.entry_type == "reassigned")
        )
    ).scalar_one()
    assert "Incident Analyst" in timeline.description or "inc_analyst_assigned" in timeline.description
    assert timeline.entry_metadata["reason"] == "Escalated for senior review"

    # Verify AuditLog row
    audit = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.target_id == inc.id, AuditLog.action == "incident.reassign")
        )
    ).scalar_one()
    assert audit.details["after"]["reason"] == "Escalated for senior review"


async def test_admin_assets_list_and_kpis(client, db_session):
    from app.models import AssetCriticality, AssetType

    org1 = await make_organization(db_session, name="Org One")
    org2 = await make_organization(db_session, name="Org Two")
    super_tok = await _super_admin_token(client, db_session, email="super_assets@example.com")

    a1 = Asset(
        organization_id=org1.id,
        name="web-server-01",
        hostname="web01.internal",
        asset_type=AssetType.server,
        criticality=AssetCriticality.critical,
        status="active",
    )
    a2 = Asset(
        organization_id=org1.id,
        name="db-server-01",
        hostname="db01.internal",
        asset_type=AssetType.database,
        criticality=AssetCriticality.high,
        status="active",
    )
    a3 = Asset(
        organization_id=org2.id,
        name="legacy-box",
        hostname="old.internal",
        asset_type=AssetType.workstation,
        criticality=AssetCriticality.low,
        status="retired",
    )
    db_session.add_all([a1, a2, a3])
    await db_session.commit()

    # 1. Non-super admin rejected
    user = await make_user(db_session, organization_id=org1.id, email="dev_assets@example.com", role=UserRole.it_developer)
    user_tok = await login(client, user.email)
    resp_unauth = await client.get("/api/v1/admin/assets", headers=auth(user_tok))
    assert resp_unauth.status_code == 403

    # 2. Super admin lists all assets
    resp = await client.get("/api/v1/admin/assets", headers=auth(super_tok))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 3
    assert body["kpis"]["total"] == 3
    assert body["kpis"]["active"] == 2
    assert body["kpis"]["retired"] == 1
    assert body["kpis"]["critical"] == 1
    assert len(body["organizations"]) >= 2

    # 3. Filter by organization
    resp_org1 = await client.get(f"/api/v1/admin/assets?organization_id={org1.id}", headers=auth(super_tok))
    assert resp_org1.status_code == 200
    assert resp_org1.json()["total"] == 2

    # 4. Filter by search query
    resp_q = await client.get("/api/v1/admin/assets?q=web01", headers=auth(super_tok))
    assert resp_q.status_code == 200
    assert resp_q.json()["total"] == 1
    assert resp_q.json()["assets"][0]["hostname"] == "web01.internal"


async def test_admin_security_overview(client, db_session):
    org = await make_organization(db_session, name="Security Org")
    super_tok = await _super_admin_token(client, db_session, email="super_sec@example.com")

    now = datetime.now(timezone.utc)
    inc = Incident(
        organization_id=org.id,
        title="Ransomware Detected",
        severity=EventSeverity.critical,
        status=IncidentStatus.investigating,
        opened_at=now,
    )
    alert = Alert(
        organization_id=org.id,
        title="Suspicious Powershell Execution",
        severity=EventSeverity.high,
        status=AlertStatus.new,
        first_seen_at=now,
        last_seen_at=now,
    )
    db_session.add_all([inc, alert])
    await db_session.commit()

    resp = await client.get("/api/v1/admin/oversight/security-overview?range=24h", headers=auth(super_tok))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kpis"]["critical_incidents"] >= 1
    assert body["kpis"]["open_alerts"] >= 1
    assert body["incidents_by_severity"]["critical"] >= 1
    assert len(body["active_incidents"]) >= 1
    assert body["active_incidents"][0]["title"] == "Ransomware Detected"
    assert len(body["recent_alerts"]) >= 1
    assert body["recent_alerts"][0]["title"] == "Suspicious Powershell Execution"

