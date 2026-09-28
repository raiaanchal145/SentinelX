"""P13 API tests: the remediation workflow over the HTTP surface.

Covers: creation (manual + auto), the transition table per role (valid
and invalid), IT cannot close, critical-close needs an approved
approval, assignment rule order + least-loaded tie-break, SLA marking
with a controllable clock, managed vs in-house visibility, internal
comments hidden from IT, cross-organization isolation, and the
audit/history/timeline rows every change writes.
"""

import datetime as dt
import uuid

import pytest

from app.models import (
    ActorType,
    Approval,
    ApprovalRiskLevel,
    ApprovalStatus,
    AssignmentRule,
    AuditLog,
    Escalation,
    EventSeverity,
    Incident,
    IncidentTimeline,
    OrganizationSettings,
    TicketComment,
    TicketStatus,
    TicketStatusHistory,
    UserRole,
)
from app.worker.ticket_jobs import ticket_sla_check
from tests.helpers import (
    TEST_PASSWORD,
    auth,
    login,
    make_admin,
    make_organization,
    make_team,
    make_user,
)

UTC = dt.timezone.utc


async def seed_soc_world(
    db_session,
    *,
    soc_mode,
    with_settings=False,
    threshold_severity=None,
    threshold_confidence=None,
):
    """A target organization (+ owner) and the SOC side that works it:
    for managed, an assigned platform SOC analyst; for in-house, the
    org's own soc_analyst. Returns (org, soc_email, it devs...)."""
    org = await make_organization(db_session, soc_mode=soc_mode)
    # Orgs created through POST /admin/organizations get default SLA
    # policies seeded; mirror that here (see app/routers/admin_organizations.py).
    from app.tickets import seed_default_sla_policies

    await seed_default_sla_policies(db_session, org.id)
    await db_session.commit()
    owner = await make_admin(
        db_session, email=f"owner-{org.id}@x.io", organization_id=org.id
    )
    if with_settings:
        db_session.add(
            OrganizationSettings(
                organization_id=org.id,
                auto_ticket_threshold=threshold_severity,
                auto_ticket_min_confidence=threshold_confidence,
            )
        )
        await db_session.commit()

    if soc_mode.value == "managed":
        from app.models import SocOrganizationAssignment

        soc_admin = await make_admin(
            db_session,
            email=f"soc-{org.id}@x.io",
            admin_level=__import__("app.models", fromlist=["AdminLevel"]).AdminLevel.platform_soc_analyst,
        )
        db_session.add(
            SocOrganizationAssignment(admin_id=soc_admin.id, organization_id=org.id)
        )
        await db_session.commit()
        soc_email = soc_admin.email
    else:
        analyst = await make_user(
            db_session,
            email=f"analyst-{org.id}@x.io",
            role=UserRole.soc_analyst,
            organization_id=org.id,
        )
        soc_email = analyst.email

    team = await make_team(db_session, organization_id=org.id, name="IT Ops")
    dev1 = await make_user(
        db_session,
        email=f"dev1-{org.id}@x.io",
        name="Dev One",
        role=UserRole.it_developer,
        organization_id=org.id,
        team_id=team.id,
    )
    dev2 = await make_user(
        db_session,
        email=f"dev2-{org.id}@x.io",
        name="Dev Two",
        role=UserRole.it_developer,
        organization_id=org.id,
        team_id=team.id,
    )
    return org, soc_email, team, dev1, dev2


async def create_ticket(client, token, org_id=None, **overrides):
    payload = {"title": "Patch the server", "organization_id": org_id}
    payload.update(overrides)
    resp = await client.post("/api/v1/tickets", json=payload, headers=auth(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Creation + priority.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_managed_org_platform_soc_creates_ticket_with_computed_priority(client, db_session):
    org, soc_email, team, dev1, dev2 = await seed_soc_world(db_session, soc_mode=__import__("app.models", fromlist=["SocMode"]).SocMode.managed)
    token = await login(client, soc_email)
    row = await create_ticket(
        client, token, org_id=str(org.id),
        severity="critical", priority=None,
    )
    assert row["status"] == "OPEN"
    # No asset, no confidence -> critical severity alone = 40 pts -> P3
    # (>= P3_MIN 35, below P2_MIN 60).
    assert row["priority"] == "P3"
    # SLA deadlines were stamped from the org's default P4 policy.
    assert row["sla"]["resolve_due_at"] is not None
    assert row["sla"]["state"] == "on_track"


@pytest.mark.asyncio
async def test_managed_org_it_can_see_and_work_platform_created_ticket(client, db_session):
    org, soc_email, team, dev1, dev2 = await seed_soc_world(db_session, soc_mode=__import__("app.models", fromlist=["SocMode"]).SocMode.managed)
    soc_token = await login(client, soc_email)
    ticket = await create_ticket(client, soc_token, org_id=str(org.id))

    it_token = await login(client, dev1.email)
    resp = await client.get(f"/api/v1/tickets/{ticket['id']}", headers=auth(it_token))
    assert resp.status_code == 200
    body = resp.json()
    # Managed org's IT sees the platform-SOC-created ticket.
    assert body["ticket"]["id"] == ticket["id"]

    # And can work it: OPEN -> INVESTIGATING -> REMEDIATION -> VERIFICATION.
    for status in ("investigating", "remediation", "verification"):
        resp = await client.post(
            f"/api/v1/tickets/{ticket['id']}/transition",
            json={"status": status},
            headers=auth(it_token),
        )
        assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "VERIFICATION"


@pytest.mark.asyncio
async def test_it_cannot_create_ticket(client, db_session):
    org, soc_email, team, dev1, dev2 = await seed_soc_world(db_session, soc_mode=__import__("app.models", fromlist=["SocMode"]).SocMode.in_house)
    it_token = await login(client, dev1.email)
    resp = await client.post(
        "/api/v1/tickets",
        json={"title": "nope"},
        headers=auth(it_token),
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] in {"soc_not_visible", "ticket_write_not_allowed", "module_not_available"}


# ---------------------------------------------------------------------------
# The transition table per role.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_it_cannot_close_ticket(client, db_session):
    org, soc_email, team, dev1, dev2 = await seed_soc_world(db_session, soc_mode=__import__("app.models", fromlist=["SocMode"]).SocMode.in_house)
    soc_token = await login(client, soc_email)
    ticket = await create_ticket(client, soc_token, org_id=str(org.id))

    it_token = await login(client, dev1.email)
    # IT walks the ticket to VERIFICATION.
    for status in ("investigating", "remediation", "verification"):
        resp = await client.post(
            f"/api/v1/tickets/{ticket['id']}/transition",
            json={"status": status},
            headers=auth(it_token),
        )
        assert resp.status_code == 200
    # IT tries to close -> 403 it_cannot_close (and NOT closed).
    resp = await client.post(
        f"/api/v1/tickets/{ticket['id']}/transition",
        json={"status": "closed"},
        headers=auth(it_token),
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "it_cannot_close"
    detail = await client.get(f"/api/v1/tickets/{ticket['id']}", headers=auth(soc_token))
    assert detail.json()["ticket"]["status"] == "VERIFICATION"

    # IT also cannot resolve.
    resp = await client.post(
        f"/api/v1/tickets/{ticket['id']}/transition",
        json={"status": "resolved"},
        headers=auth(it_token),
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "it_cannot_close"


@pytest.mark.asyncio
async def test_invalid_transition_returns_409_with_allowed_states(client, db_session):
    org, soc_email, team, dev1, dev2 = await seed_soc_world(db_session, soc_mode=__import__("app.models", fromlist=["SocMode"]).SocMode.in_house)
    soc_token = await login(client, soc_email)
    ticket = await create_ticket(client, soc_token, org_id=str(org.id))
    resp = await client.post(
        f"/api/v1/tickets/{ticket['id']}/transition",
        json={"status": "closed"},
        headers=auth(soc_token),
    )
    assert resp.status_code == 409
    body = resp.json()["detail"]
    assert body["code"] == "invalid_ticket_transition"
    assert "allowed_next_states" in body


@pytest.mark.asyncio
async def test_soc_verifies_and_closes_full_cycle(client, db_session):
    org, soc_email, team, dev1, dev2 = await seed_soc_world(db_session, soc_mode=__import__("app.models", fromlist=["SocMode"]).SocMode.in_house)
    soc_token = await login(client, soc_email)
    ticket = await create_ticket(client, soc_token, org_id=str(org.id))
    it_token = await login(client, dev1.email)
    for status in ("investigating", "remediation", "verification"):
        await client.post(
            f"/api/v1/tickets/{ticket['id']}/transition", json={"status": status},
            headers=auth(it_token),
        )
    # SOC verifies the fix -> RESOLVED.
    resp = await client.post(
        f"/api/v1/tickets/{ticket['id']}/verify",
        json={"result": "verified", "notes": "Payload removed, host clean.", "method": "manual"},
        headers=auth(soc_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "RESOLVED"
    # SOC closes.
    resp = await client.post(
        f"/api/v1/tickets/{ticket['id']}/transition",
        json={"status": "closed", "note": "Verified fix"},
        headers=auth(soc_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "CLOSED"
    # SOC reopens -> OPEN.
    resp = await client.post(
        f"/api/v1/tickets/{ticket['id']}/transition",
        json={"status": "open"},
        headers=auth(soc_token),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "OPEN"

    # History + audit trail exist for every change.
    detail = (await client.get(f"/api/v1/tickets/{ticket['id']}", headers=auth(soc_token))).json()
    statuses = [h["to_status"] for h in detail["status_history"]]
    assert statuses[0] == "OPEN"
    assert "VERIFICATION" in statuses and "RESOLVED" in statuses and "CLOSED" in statuses and "OPEN" in statuses
    from sqlalchemy import select as _select

    audits = (
        await db_session.execute(
            _select(AuditLog).where(
                AuditLog.action.in_(["ticket.create", "ticket.transition", "ticket.verify"]),
                AuditLog.target_id == uuid.UUID(ticket["id"]),
            )
        )
    ).scalars().all()
    assert len(audits) >= 3


@pytest.mark.asyncio
async def test_it_cannot_verify(client, db_session):
    org, soc_email, team, dev1, dev2 = await seed_soc_world(db_session, soc_mode=__import__("app.models", fromlist=["SocMode"]).SocMode.in_house)
    soc_token = await login(client, soc_email)
    ticket = await create_ticket(client, soc_token, org_id=str(org.id))
    it_token = await login(client, dev1.email)
    await client.post(f"/api/v1/tickets/{ticket['id']}/transition", json={"status": "investigating"}, headers=auth(it_token))
    await client.post(f"/api/v1/tickets/{ticket['id']}/transition", json={"status": "verification"}, headers=auth(it_token))
    resp = await client.post(
        f"/api/v1/tickets/{ticket['id']}/verify", json={"result": "verified"}, headers=auth(it_token)
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "it_cannot_close"


# ---------------------------------------------------------------------------
# Critical close needs an approved approval.
# ---------------------------------------------------------------------------


async def _walk_to_verification(client, it_token, ticket_id):
    for status in ("investigating", "remediation", "verification"):
        resp = await client.post(
            f"/api/v1/tickets/{ticket_id}/transition", json={"status": status},
            headers=auth(it_token),
        )
        assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_critical_ticket_cannot_close_without_approval(client, db_session):
    org, soc_email, team, dev1, dev2 = await seed_soc_world(db_session, soc_mode=__import__("app.models", fromlist=["SocMode"]).SocMode.in_house)
    soc_token = await login(client, soc_email)
    ticket = await create_ticket(
        client, soc_token, org_id=str(org.id), severity="critical", priority="P1",
    )
    it_token = await login(client, dev1.email)
    await _walk_to_verification(client, it_token, ticket["id"])
    # SOC verifies -> RESOLVED, then tries to close -> blocked.
    await client.post(f"/api/v1/tickets/{ticket['id']}/verify", json={"result": "verified"}, headers=auth(soc_token))
    resp = await client.post(
        f"/api/v1/tickets/{ticket['id']}/transition", json={"status": "closed"}, headers=auth(soc_token),
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "close_approval_required"


@pytest.mark.asyncio
async def test_critical_ticket_closes_with_approved_approval(client, db_session):
    org, soc_email, team, dev1, dev2 = await seed_soc_world(db_session, soc_mode=__import__("app.models", fromlist=["SocMode"]).SocMode.in_house)
    soc_token = await login(client, soc_email)
    ticket = await create_ticket(
        client, soc_token, org_id=str(org.id), severity="critical", priority="P1",
    )
    it_token = await login(client, dev1.email)
    await _walk_to_verification(client, it_token, ticket["id"])
    await client.post(f"/api/v1/tickets/{ticket['id']}/verify", json={"result": "verified"}, headers=auth(soc_token))

    # The SOC requests the closure via the API: a PENDING ticket_close
    # approval row the security manager or owner then decides.
    resp = await client.post(
        f"/api/v1/tickets/{ticket['id']}/close-request",
        json={"notes": "fix verified, requesting close"},
        headers=auth(soc_token),
    )
    assert resp.status_code == 201, resp.text
    approval_id = resp.json()["id"]

    # Security manager approves via the decision endpoint.
    sm = await make_user(
        db_session, email=f"sm-{org.id}@x.io", role=UserRole.security_manager, organization_id=org.id,
    )
    sm_token = await login(client, sm.email)
    resp = await client.post(
        f"/api/v1/approvals/{approval_id}/decision",
        json={"decision": "approved", "notes": "ok"},
        headers=auth(sm_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"

    # Now the SOC can close.
    resp = await client.post(
        f"/api/v1/tickets/{ticket['id']}/transition", json={"status": "closed"}, headers=auth(soc_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "CLOSED"


@pytest.mark.asyncio
async def test_close_request_endpoint_lifecycle(client, db_session):
    """POST /tickets/{id}/close-request: SOC-only, P1-only, one pending
    request at a time -- the row it creates is decided via /approvals."""
    org, soc_email, team, dev1, dev2 = await seed_soc_world(db_session, soc_mode=__import__("app.models", fromlist=["SocMode"]).SocMode.in_house)
    soc_token = await login(client, soc_email)
    ticket = await create_ticket(
        client, soc_token, org_id=str(org.id), severity="critical", priority="P1",
    )
    it_token = await login(client, dev1.email)

    # IT cannot request closure.
    resp = await client.post(
        f"/api/v1/tickets/{ticket['id']}/close-request", json={}, headers=auth(it_token),
    )
    assert resp.status_code == 403

    # A non-critical ticket is 422 (no approval needed).
    low = await create_ticket(client, soc_token, org_id=str(org.id), severity="low")
    resp = await client.post(
        f"/api/v1/tickets/{low['id']}/close-request", json={}, headers=auth(soc_token),
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "close_approval_not_required"

    # The critical one: 201, then a second request is 409.
    resp = await client.post(
        f"/api/v1/tickets/{ticket['id']}/close-request",
        json={"notes": "please approve"},
        headers=auth(soc_token),
    )
    assert resp.status_code == 201, resp.text
    approval_id = resp.json()["id"]
    resp = await client.post(
        f"/api/v1/tickets/{ticket['id']}/close-request", json={}, headers=auth(soc_token),
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "close_request_already_pending"

    # Owner approves; the audit trail records the request.
    owner_token = await login(client, f"owner-{org.id}@x.io")
    resp = await client.post(
        f"/api/v1/approvals/{approval_id}/decision",
        json={"decision": "approved", "notes": "ok"},
        headers=auth(owner_token),
    )
    assert resp.status_code == 200, resp.text
    from sqlalchemy import select as _select

    audits = (
        await db_session.execute(
            _select(AuditLog).where(
                AuditLog.action == "ticket.close_request",
                AuditLog.target_id == uuid.UUID(ticket["id"]),
            )
        )
    ).scalars().all()
    assert len(audits) == 1


@pytest.mark.asyncio
async def test_soc_analyst_cannot_decide_approvals(client, db_session):
    org, soc_email, team, dev1, dev2 = await seed_soc_world(db_session, soc_mode=__import__("app.models", fromlist=["SocMode"]).SocMode.in_house)
    approval = Approval(
        organization_id=org.id,
        requested_by_type=ActorType.system,
        action_type="ticket_close",
        action_payload={"ticket_id": str(uuid.uuid4())},
        risk_level=ApprovalRiskLevel.high,
    )
    db_session.add(approval)
    await db_session.commit()
    soc_token = await login(client, soc_email)
    resp = await client.post(
        f"/api/v1/approvals/{approval.id}/decision",
        json={"decision": "approved"},
        headers=auth(soc_token),
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "approvals_decide_not_allowed"


# ---------------------------------------------------------------------------
# Assignment: rule order + least-loaded tie-break + isolation.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assignment_rules_evaluated_in_priority_order(client, db_session):
    org, soc_email, team, dev1, dev2 = await seed_soc_world(db_session, soc_mode=__import__("app.models", fromlist=["SocMode"]).SocMode.in_house)
    other_team = await make_team(db_session, organization_id=org.id, name="Second Team")
    db_session.add_all(
        [
            AssignmentRule(
                organization_id=org.id, name="second-wins-if-first-disabled",
                match_conditions=[{"field": "priority", "op": "in", "value": ["P1", "P2"]}],
                assign_to_team_id=other_team.id, priority_order=2, enabled=True,
            ),
            AssignmentRule(
                organization_id=org.id, name="first-p1",
                match_conditions=[{"field": "priority", "op": "eq", "value": "P1"}],
                assign_to_team_id=team.id, priority_order=1, enabled=True,
            ),
        ]
    )
    await db_session.commit()

    soc_token = await login(client, soc_email)
    ticket = await create_ticket(
        client, soc_token, org_id=str(org.id), severity="critical", priority="P1",
    )
    resp = await client.post(f"/api/v1/tickets/{ticket['id']}/auto-assign", headers=auth(soc_token))
    assert resp.status_code == 200, resp.text
    row = resp.json()
    # priority_order 1 ran first and matched.
    assert row["assigned_team_id"] == str(team.id)
    assert row["status"] == "ASSIGNED"


@pytest.mark.asyncio
async def test_least_loaded_member_tie_break(client, db_session):
    org, soc_email, team, dev1, dev2 = await seed_soc_world(db_session, soc_mode=__import__("app.models", fromlist=["SocMode"]).SocMode.in_house)
    db_session.add(
        AssignmentRule(
            organization_id=org.id,
            name="all",
            match_conditions=[{"field": "category", "op": "ne", "value": "__never__"}],
            assign_to_team_id=team.id,
            priority_order=1,
        )
    )
    await db_session.commit()
    soc_token = await login(client, soc_email)

    # Give dev1 one open ticket; the rule should pick dev2 (fewest open).
    first = await create_ticket(client, soc_token, org_id=str(org.id))
    await client.post(
        f"/api/v1/tickets/{first['id']}/assign",
        json={"team_id": str(team.id), "user_id": str(dev1.id)},
        headers=auth(soc_token),
    )
    second = await create_ticket(client, soc_token, org_id=str(org.id))
    resp = await client.post(f"/api/v1/tickets/{second['id']}/auto-assign", headers=auth(soc_token))
    assert resp.status_code == 200
    assert resp.json()["assigned_user_id"] == str(dev2.id)

    # dev2 now also has one -> tie -> deterministic by name: Dev One.
    third = await create_ticket(client, soc_token, org_id=str(org.id))
    resp = await client.post(f"/api/v1/tickets/{third['id']}/auto-assign", headers=auth(soc_token))
    assert resp.status_code == 200
    assert resp.json()["assigned_user_id"] in {str(dev1.id), str(dev2.id)}


@pytest.mark.asyncio
async def test_cannot_assign_user_of_another_organization(client, db_session):
    org, soc_email, team, dev1, dev2 = await seed_soc_world(db_session, soc_mode=__import__("app.models", fromlist=["SocMode"]).SocMode.in_house)
    foreign_org = await make_organization(db_session, name="Other Co")
    foreign_dev = await make_user(
        db_session, email=f"dev-{foreign_org.id}@x.io",
        role=UserRole.it_developer, organization_id=foreign_org.id,
    )
    soc_token = await login(client, soc_email)
    ticket = await create_ticket(client, soc_token, org_id=str(org.id))
    resp = await client.post(
        f"/api/v1/tickets/{ticket['id']}/assign",
        json={"user_id": str(foreign_dev.id)},
        headers=auth(soc_token),
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "assignee_not_in_scope"


# ---------------------------------------------------------------------------
# Visibility: internal notes hidden from IT; managed vs in-house; isolation.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_internal_comments_hidden_from_it(client, db_session):
    org, soc_email, team, dev1, dev2 = await seed_soc_world(db_session, soc_mode=__import__("app.models", fromlist=["SocMode"]).SocMode.in_house)
    soc_token = await login(client, soc_email)
    ticket = await create_ticket(client, soc_token, org_id=str(org.id))

    await client.post(
        f"/api/v1/tickets/{ticket['id']}/comments",
        json={"body": "SOC-only suspicion", "is_internal": True},
        headers=auth(soc_token),
    )
    await client.post(
        f"/api/v1/tickets/{ticket['id']}/comments",
        json={"body": "Shared with IT", "is_internal": False},
        headers=auth(soc_token),
    )

    it_token = await login(client, dev1.email)
    body = (await client.get(f"/api/v1/tickets/{ticket['id']}", headers=auth(it_token))).json()
    texts = [c["body"] for c in body["comments"]]
    assert "Shared with IT" in texts
    assert "SOC-only suspicion" not in texts

    soc_view = (await client.get(f"/api/v1/tickets/{ticket['id']}", headers=auth(soc_token))).json()
    assert len(soc_view["comments"]) == 2


@pytest.mark.asyncio
async def test_it_writes_shared_comments_only(client, db_session):
    org, soc_email, team, dev1, dev2 = await seed_soc_world(db_session, soc_mode=__import__("app.models", fromlist=["SocMode"]).SocMode.in_house)
    soc_token = await login(client, soc_email)
    ticket = await create_ticket(client, soc_token, org_id=str(org.id))
    it_token = await login(client, dev1.email)
    resp = await client.post(
        f"/api/v1/tickets/{ticket['id']}/comments",
        json={"body": "fix deployed", "is_internal": True},
        headers=auth(it_token),
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "internal_comment_not_allowed"
    resp = await client.post(
        f"/api/v1/tickets/{ticket['id']}/comments",
        json={"body": "fix deployed", "is_internal": False},
        headers=auth(it_token),
    )
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_cross_organization_ticket_is_404(client, db_session):
    org_a, soc_a, *_ = await seed_soc_world(db_session, soc_mode=__import__("app.models", fromlist=["SocMode"]).SocMode.in_house)
    org_b, soc_b, *_ = await seed_soc_world(db_session, soc_mode=__import__("app.models", fromlist=["SocMode"]).SocMode.in_house)
    token_a = await login(client, soc_a)
    ticket = await create_ticket(client, token_a, org_id=str(org_a.id))
    token_b = await login(client, soc_b)
    resp = await client.get(f"/api/v1/tickets/{ticket['id']}", headers=auth(token_b))
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "ticket_not_found"


@pytest.mark.asyncio
async def test_unassigned_platform_soc_sees_empty_queue(client, db_session):
    await make_organization(db_session, soc_mode=__import__("app.models", fromlist=["SocMode"]).SocMode.managed)
    AdminLevel = __import__("app.models", fromlist=["AdminLevel"]).AdminLevel
    soc_admin = await make_admin(
        db_session, email="lonely-soc@x.io", admin_level=AdminLevel.platform_soc_analyst
    )
    token = await login(client, soc_admin.email)
    resp = await client.get("/api/v1/tickets", headers=auth(token))
    assert resp.status_code == 200
    assert resp.json() == {"tickets": [], "total": 0}


# ---------------------------------------------------------------------------
# Auto-creation (thresholds + duplicate guard).
# ---------------------------------------------------------------------------


async def _make_incident(client, token, org_id, *, severity, confidence):
    payload = {
        "title": "Breached",
        "severity": severity,
        "organization_id": org_id,
        "confidence": confidence,
    }
    resp = await client.post("/api/v1/incidents", json=payload, headers=auth(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_auto_ticket_created_when_thresholds_pass(client, db_session):
    SocMode = __import__("app.models", fromlist=["SocMode"]).SocMode
    org, soc_email, team, dev1, dev2 = await seed_soc_world(
        db_session, soc_mode=SocMode.in_house, with_settings=True,
        threshold_severity=EventSeverity.high, threshold_confidence=0.8,
    )
    token = await login(client, soc_email)
    incident = await _make_incident(client, token, str(org.id), severity="critical", confidence=0.95)
    resp = await client.get("/api/v1/tickets", headers=auth(token))
    tickets = resp.json()["tickets"]
    auto = [t for t in tickets if t["incident_id"] == incident["id"]]
    assert len(auto) == 1
    assert auto[0]["title"].startswith("[Auto]")

    # Timeline records the auto-creation.
    detail = (await client.get(f"/api/v1/incidents/{incident['id']}", headers=auth(token))).json()
    assert any(e["entry_type"] == "ticket_created" for e in detail["timeline"])


@pytest.mark.asyncio
async def test_no_auto_ticket_below_thresholds(client, db_session):
    SocMode = __import__("app.models", fromlist=["SocMode"]).SocMode
    org, soc_email, *_ = await seed_soc_world(
        db_session, soc_mode=SocMode.in_house, with_settings=True,
        threshold_severity=EventSeverity.critical, threshold_confidence=0.9,
    )
    token = await login(client, soc_email)
    await _make_incident(client, token, str(org.id), severity="high", confidence=0.95)
    resp = await client.get("/api/v1/tickets", headers=auth(token))
    assert resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_no_duplicate_auto_ticket_for_same_incident(client, db_session):
    SocMode = __import__("app.models", fromlist=["SocMode"]).SocMode
    org, soc_email, *_ = await seed_soc_world(
        db_session, soc_mode=SocMode.in_house, with_settings=True,
        threshold_severity=EventSeverity.high, threshold_confidence=0.5,
    )
    token = await login(client, soc_email)
    await _make_incident(client, token, str(org.id), severity="high", confidence=0.9)
    await _make_incident(client, token, str(org.id), severity="high", confidence=0.9)
    resp = await client.get("/api/v1/tickets", headers=auth(token))
    assert resp.json()["total"] == 2  # two incidents, one ticket each


# ---------------------------------------------------------------------------
# SLA marking with a controllable clock.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sla_worker_marks_at_risk_then_breaches_with_escalation(client, db_session):
    SocMode = __import__("app.models", fromlist=["SocMode"]).SocMode
    org, soc_email, team, dev1, dev2 = await seed_soc_world(db_session, soc_mode=SocMode.in_house)
    soc_token = await login(client, soc_email)
    ticket = await create_ticket(
        client, soc_token, org_id=str(org.id), severity="critical", priority="P1",
    )
    from app.models import Ticket as TicketModel

    # The worker job must touch the TEST database, never the dev one:
    # pass the conftest session factory explicitly. It shares the engine
    # (NullPool) but opens its OWN connection -- so this session must not
    # hold a write transaction on the ticket rows while the job runs.
    # Expire + commit here to release any open transaction first.
    db_session.expire_all()
    await db_session.commit()
    db_ticket = await db_session.get(TicketModel, uuid.UUID(ticket["id"]))
    resolve_due = db_ticket.resolve_due_at
    created = db_ticket.created_at
    # created_at is a naive `timestamp` (server_default now()); treat it
    # as UTC so it can be mixed with the tz-aware deadline columns.
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    assert resolve_due is not None
    # Detach fully so the fixture session holds no locks during the job.
    db_session.expunge_all()

    from tests.conftest import TestSessionLocal

    # T0: on track.
    result = await ticket_sla_check({}, session_factory=TestSessionLocal, now=created)
    assert result["marked_at_risk"] == 0

    # 85% of the resolve window: at-risk.
    window = (resolve_due - created).total_seconds()
    at_risk_time = created + dt.timedelta(seconds=0.85 * window)
    result = await ticket_sla_check({}, now=at_risk_time, session_factory=TestSessionLocal)
    assert result["marked_breached"] == 0

    # Past the deadline: breached + one escalation row.
    result = await ticket_sla_check({}, now=resolve_due + dt.timedelta(minutes=1), session_factory=TestSessionLocal)
    assert result["marked_breached"] == 1
    assert result["escalations"] == 1

    # Re-running does not double-escalate (idempotent).
    result = await ticket_sla_check({}, now=resolve_due + dt.timedelta(minutes=2), session_factory=TestSessionLocal)
    assert result["escalations"] == 0

    from sqlalchemy import select as _select

    escalations = (
        await db_session.execute(_select(Escalation).where(Escalation.ticket_id == db_ticket.id))
    ).scalars().all()
    assert len(escalations) == 1
    assert escalations[0].reason.startswith("SLA breach:")


# ---------------------------------------------------------------------------
# Escalate endpoint.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_manual_escalation_endpoint(client, db_session):
    SocMode = __import__("app.models", fromlist=["SocMode"]).SocMode
    org, soc_email, *_ = await seed_soc_world(db_session, soc_mode=SocMode.in_house)
    soc_token = await login(client, soc_email)
    ticket = await create_ticket(client, soc_token, org_id=str(org.id))
    resp = await client.post(
        f"/api/v1/tickets/{ticket['id']}/escalate",
        json={"reason": "Needs vendor engagement"},
        headers=auth(soc_token),
    )
    assert resp.status_code == 201
    from sqlalchemy import select as _select

    rows = (
        await db_session.execute(_select(Escalation).where(Escalation.ticket_id == uuid.UUID(ticket["id"])))
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].reason == "Needs vendor engagement"


# ---------------------------------------------------------------------------
# Tasks.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_task_crud_by_it_and_soc(client, db_session):
    SocMode = __import__("app.models", fromlist=["SocMode"]).SocMode
    org, soc_email, team, dev1, dev2 = await seed_soc_world(db_session, soc_mode=SocMode.in_house)
    soc_token = await login(client, soc_email)
    ticket = await create_ticket(client, soc_token, org_id=str(org.id))
    it_token = await login(client, dev1.email)

    # IT creates a task assigned to their org's user.
    resp = await client.post(
        f"/api/v1/tickets/{ticket['id']}/tasks",
        json={"title": "Remove malware", "assignee_user_id": str(dev2.id)},
        headers=auth(it_token),
    )
    assert resp.status_code == 201, resp.text
    task_id = resp.json()["id"]

    # Complete it.
    resp = await client.patch(
        f"/api/v1/tickets/{ticket['id']}/tasks/{task_id}",
        json={"status": "completed"},
        headers=auth(it_token),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"

    # Delete it.
    resp = await client.delete(
        f"/api/v1/tickets/{ticket['id']}/tasks/{task_id}", headers=auth(soc_token)
    )
    assert resp.status_code == 204

    # Task assignee outside the org is refused.
    foreign_org = await make_organization(db_session, name="Foreign")
    foreign_user = await make_user(
        db_session, email=f"u-{foreign_org.id}@x.io", organization_id=foreign_org.id
    )
    resp = await client.post(
        f"/api/v1/tickets/{ticket['id']}/tasks",
        json={"title": "x", "assignee_user_id": str(foreign_user.id)},
        headers=auth(soc_token),
    )
    assert resp.status_code == 422
