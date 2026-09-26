"""
The incidents milestone (docs/API_CONTRACT.md "Incidents"):

1. creation: manual + from-alerts (alerts become TRIAGED at creation);
2. the transition map: every valid edge, every invalid move (409 with
   the allowed next states), the payload requirements (resolution
   summary to close, reason for FALSE_POSITIVE/DUPLICATE, parent for
   DUPLICATE);
3. role x transition: managed org worked by platform SOC only, in-house
   by its own soc_analyst, owner read-only, security_manager read-only
   + escalation;
4. visibility/isolation: cross-org ids are 404, platform roles filter
   by organization_id, internal comments hidden from non-SOC eyes;
5. side effects: alert status follows the incident (triaged at
   creation, converted on resolve/close); timeline + audit rows on
   every change; merge moves links and marks the duplicate.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import (
    AdminLevel,
    Alert,
    AlertStatus,
    AuditLog,
    EventSeverity,
    Incident,
    IncidentAlert,
    IncidentStatus,
    IncidentTimeline,
    Organization,
    SocMode,
    UserRole,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.helpers import auth, login, make_admin, make_organization, make_user  # noqa: E402

pytestmark = pytest.mark.asyncio

NOW = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Seed helpers.
# ---------------------------------------------------------------------------


async def _make_alert(db_session, org, *, rule_name="Test rule", status=AlertStatus.new):
    alert = Alert(
        organization_id=org.id,
        rule_name=rule_name,
        kind="detection",
        severity=EventSeverity.high,
        status=status,
        title=f"{rule_name} -- user=test",
        first_seen_at=NOW,
        last_seen_at=NOW,
        event_count=1,
        dedup_key=f"{rule_name}:{uuid.uuid4()}",
    )
    db_session.add(alert)
    await db_session.commit()
    await db_session.refresh(alert)
    return alert


async def _token_for(client, db_session, *, org=None, level=None, role=None):
    if level == AdminLevel.super_admin:
        admin = await make_admin(db_session, email=f"sa-{uuid.uuid4().hex[:8]}@x.io", admin_level=level)
    elif level == AdminLevel.platform_soc_analyst:
        admin = await make_admin(db_session, email=f"psa-{uuid.uuid4().hex[:8]}@x.io", admin_level=level)
    elif level == AdminLevel.organization_admin:
        admin = await make_admin(
            db_session, email=f"owner-{uuid.uuid4().hex[:8]}@x.io", admin_level=level, organization_id=org.id
        )
    else:
        user = await make_user(db_session, email=f"u-{uuid.uuid4().hex[:8]}@x.io", role=role, organization_id=org.id)
        return await login(client, user.email)
    return await login(client, admin.email)


async def _assign_platform_soc(db_session, admin, org):
    from app.models import SocOrganizationAssignment

    db_session.add(SocOrganizationAssignment(admin_id=admin.id, organization_id=org.id))
    await db_session.commit()


async def _create_incident(client, token, *, title="Test incident", org=None, **extra):
    payload = {"title": title, **extra}
    if org is not None:
        payload["organization_id"] = str(org.id)
    resp = await client.post("/api/v1/incidents", json=payload, headers=auth(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _transition(status, **extra):
    return {"status": status, **extra}


# ---------------------------------------------------------------------------
# Creation.
# ---------------------------------------------------------------------------


async def test_manual_create_by_in_house_analyst(db_session, client):
    org = await make_organization(db_session, soc_mode=SocMode.in_house)
    token = await _token_for(client, db_session, org=org, role=UserRole.soc_analyst)

    body = await _create_incident(
        client, token, title="Manual incident", description="d", severity="high", priority="P2", category="intrusion"
    )
    assert body["status"] == "NEW"
    assert body["severity"] == "high"
    assert body["priority"] == "P2"
    # A created timeline row and an audit entry exist.
    timeline = (
        await db_session.execute(select(IncidentTimeline).where(IncidentTimeline.entry_type == "created"))
    ).scalars().all()
    assert len(timeline) == 1
    audits = (
        await db_session.execute(select(AuditLog).where(AuditLog.action == "incident.create"))
    ).scalars().all()
    assert len(audits) == 1


async def test_create_requires_organization_id_for_platform_role(db_session, client):
    org = await make_organization(db_session, soc_mode=SocMode.managed)
    admin_email = f"psa-{uuid.uuid4().hex[:8]}@x.io"
    admin = await make_admin(db_session, email=admin_email, admin_level=AdminLevel.platform_soc_analyst)
    await _assign_platform_soc(db_session, admin, org)
    token = await login(client, admin_email)

    # An assigned platform SOC analyst must name the organization.
    resp = await client.post("/api/v1/incidents", json={"title": "x"}, headers=auth(token))
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "organization_id_required"

    # ... and is refused for an organization they are NOT assigned to.
    other = await make_organization(db_session, soc_mode=SocMode.managed, name="Other")
    resp = await client.post(
        "/api/v1/incidents", json={"title": "x", "organization_id": str(other.id)}, headers=auth(token)
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "organization_not_found"
    _ = org


async def test_create_platform_role_with_organization_id(db_session, client):
    org = await make_organization(db_session, soc_mode=SocMode.managed)
    admin_email = f"psa-{uuid.uuid4().hex[:8]}@x.io"
    from tests.helpers import make_admin as _mk

    admin = await _mk(db_session, email=admin_email, admin_level=AdminLevel.platform_soc_analyst)
    await _assign_platform_soc(db_session, admin, org)
    token = await login(client, admin.email)

    body = await _create_incident(client, token, org=org, title="Platform incident")
    assert body["organization_id"] == str(org.id)
    assert body["created_by_type"] == "admin"


async def test_create_from_alerts_marks_alerts_triaged(db_session, client):
    org = await make_organization(db_session, soc_mode=SocMode.in_house)
    a1 = await _make_alert(db_session, org)
    a2 = await _make_alert(db_session, org, rule_name="Second rule")
    token = await _token_for(client, db_session, org=org, role=UserRole.soc_analyst)

    resp = await client.post(
        "/api/v1/incidents/from-alerts",
        json={"alert_ids": [str(a1.id), str(a2.id)], "title": "Brute force campaign", "priority": "P1"},
        headers=auth(token),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "NEW"
    assert body["severity"] == "high"  # max of the linked alerts

    await db_session.refresh(a1)
    await db_session.refresh(a2)
    assert a1.status == AlertStatus.triaged
    assert a2.status == AlertStatus.triaged

    detail = await client.get(f"/api/v1/incidents/{body['id']}", headers=auth(token))
    assert detail.status_code == 200
    assert len(detail.json()["alerts"]) == 2


async def test_from_alerts_rejects_cross_org_and_converted(db_session, client):
    org_a = await make_organization(db_session, soc_mode=SocMode.in_house, name="A")
    org_b = await make_organization(db_session, soc_mode=SocMode.in_house, name="B")
    token_a = await _token_for(client, db_session, org=org_a, role=UserRole.soc_analyst)

    other = await _make_alert(db_session, org_b)
    resp = await client.post(
        "/api/v1/incidents/from-alerts", json={"alert_ids": [str(other.id)]}, headers=auth(token_a)
    )
    assert resp.status_code == 404  # existence never leaked

    converted = await _make_alert(db_session, org_a, status=AlertStatus.converted)
    resp = await client.post(
        "/api/v1/incidents/from-alerts", json={"alert_ids": [str(converted.id)]}, headers=auth(token_a)
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "alert_already_converted"


# ---------------------------------------------------------------------------
# The transition map -- valid edges.
# ---------------------------------------------------------------------------


async def _incident_for(client, db_session, org, token) -> dict:
    return await _create_incident(client, token, org=org)


async def test_happy_path_to_closed(db_session, client):
    org = await make_organization(db_session, soc_mode=SocMode.in_house)
    token = await _token_for(client, db_session, org=org, role=UserRole.soc_analyst)
    body = await _incident_for(client, db_session, org, token)
    iid = body["id"]

    for status in ("TRIAGED", "INVESTIGATING", "CONTAINMENT", "REMEDIATION", "VERIFICATION"):
        resp = await client.post(f"/api/v1/incidents/{iid}/transition", json=_transition(status), headers=auth(token))
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == status

    # RESOLVED without a summary is fine (only CLOSED requires one).
    resp = await client.post(f"/api/v1/incidents/{iid}/transition", json=_transition("RESOLVED"), headers=auth(token))
    assert resp.status_code == 200

    # CLOSED requires the resolution summary (422 without).
    resp = await client.post(f"/api/v1/incidents/{iid}/transition", json=_transition("CLOSED"), headers=auth(token))
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "resolution_summary_required"

    resp = await client.post(
        f"/api/v1/incidents/{iid}/transition",
        json=_transition("CLOSED", resolution_summary="Root cause fixed, patches deployed."),
        headers=auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "CLOSED"


async def test_false_positive_and_duplicate_require_reason(db_session, client):
    org = await make_organization(db_session, soc_mode=SocMode.in_house)
    token = await _token_for(client, db_session, org=org, role=UserRole.soc_analyst)

    fp = await _incident_for(client, db_session, org, token)
    resp = await client.post(f"/api/v1/incidents/{fp['id']}/transition", json=_transition("FALSE_POSITIVE"), headers=auth(token))
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "closure_reason_required"

    resp = await client.post(
        f"/api/v1/incidents/{fp['id']}/transition", json=_transition("FALSE_POSITIVE", reason="Duplicate alert logic"), headers=auth(token)
    )
    assert resp.status_code == 200

    dup = await _incident_for(client, db_session, org, token)
    parent = await _incident_for(client, db_session, org, token)

    resp = await client.post(
        f"/api/v1/incidents/{dup['id']}/transition", json=_transition("DUPLICATE", reason="same"), headers=auth(token)
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "duplicate_parent_required"

    resp = await client.post(
        f"/api/v1/incidents/{dup['id']}/transition",
        json=_transition("DUPLICATE", reason="same", parent_incident_id=dup["id"]),
        headers=auth(token),
    )
    assert resp.status_code == 422  # self-parent refused
    assert resp.json()["detail"]["code"] == "duplicate_parent_invalid"

    resp = await client.post(
        f"/api/v1/incidents/{dup['id']}/transition",
        json=_transition("DUPLICATE", reason="same campaign", parent_incident_id=parent["id"]),
        headers=auth(token),
    )
    assert resp.status_code == 200

    # Terminal: no way out of FALSE_POSITIVE/DUPLICATE.
    resp = await client.post(f"/api/v1/incidents/{fp['id']}/transition", json=_transition("REOPENED"), headers=auth(token))
    assert resp.status_code == 409


async def test_invalid_transitions_409_with_allowed_states(db_session, client):
    org = await make_organization(db_session, soc_mode=SocMode.in_house)
    token = await _token_for(client, db_session, org=org, role=UserRole.soc_analyst)
    body = await _incident_for(client, db_session, org, token)

    # NEW -> CLOSED is not a legal edge.
    resp = await client.post(
        f"/api/v1/incidents/{body['id']}/transition",
        json=_transition("CLOSED", resolution_summary="premature"),
        headers=auth(token),
    )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["code"] == "invalid_incident_transition"
    assert set(detail["allowed_next_states"]) == {"TRIAGED", "INVESTIGATING", "FALSE_POSITIVE", "DUPLICATE"}

    # Unknown status name is 400, not 409.
    resp = await client.post(f"/api/v1/incidents/{body['id']}/transition", json=_transition("WAT"), headers=auth(token))
    assert resp.status_code == 400


async def test_reopen_from_resolved_and_closed(db_session, client):
    org = await make_organization(db_session, soc_mode=SocMode.in_house)
    token = await _token_for(client, db_session, org=org, role=UserRole.soc_analyst)

    for end_status, via in (
        ("RESOLVED", ["CONTAINMENT", "REMEDIATION", "VERIFICATION", "RESOLVED"]),
        ("CLOSED", ["CONTAINMENT", "REMEDIATION", "VERIFICATION", "RESOLVED"]),
    ):
        body = await _incident_for(client, db_session, org, token)
        for status in ("TRIAGED", "INVESTIGATING", *via):
            resp = await client.post(f"/api/v1/incidents/{body['id']}/transition", json=_transition(status), headers=auth(token))
            assert resp.status_code == 200, (end_status, status, resp.text)
        if end_status == "CLOSED":
            await client.post(
                f"/api/v1/incidents/{body['id']}/transition",
                json=_transition("CLOSED", resolution_summary="done"),
                headers=auth(token),
            )
        resp = await client.post(f"/api/v1/incidents/{body['id']}/transition", json=_transition("REOPENED"), headers=auth(token))
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "REOPENED"

        detail = await client.get(f"/api/v1/incidents/{body['id']}", headers=auth(token))
        row = detail.json()["incident"]
        assert row["closure_reason"] is None and row["closed_at"] is None


async def test_escalated_round_trip(db_session, client):
    """ESCALATED is reachable from TRIAGED and later active states (not
    from NEW), and the owning team picks it back up."""
    org = await make_organization(db_session, soc_mode=SocMode.in_house)
    token = await _token_for(client, db_session, org=org, role=UserRole.soc_analyst)
    body = await _incident_for(client, db_session, org, token)

    # NEW -> ESCALATED is not a legal edge (triage first).
    resp = await client.post(f"/api/v1/incidents/{body['id']}/transition", json=_transition("ESCALATED"), headers=auth(token))
    assert resp.status_code == 409

    resp = await client.post(f"/api/v1/incidents/{body['id']}/transition", json=_transition("TRIAGED"), headers=auth(token))
    assert resp.status_code == 200
    resp = await client.post(f"/api/v1/incidents/{body['id']}/transition", json=_transition("ESCALATED"), headers=auth(token))
    assert resp.status_code == 200
    resp = await client.post(f"/api/v1/incidents/{body['id']}/transition", json=_transition("INVESTIGATING"), headers=auth(token))
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Role x transition matrix.
# ---------------------------------------------------------------------------


async def test_managed_org_routing(db_session, client):
    """Managed org: assigned platform SOC writes; owner reads (403 on
    writes); security_manager reads + may request ESCALATED only;
    in-house soc_analyst of another org sees nothing (404)."""
    org = await make_organization(db_session, soc_mode=SocMode.managed)
    admin_email = f"psa-{uuid.uuid4().hex[:8]}@x.io"
    platform_admin = await make_admin(db_session, email=admin_email, admin_level=AdminLevel.platform_soc_analyst)
    await _assign_platform_soc(db_session, platform_admin, org)
    platform_token = await login(client, admin_email)

    incident = await _create_incident(client, platform_token, org=org)

    # Platform SOC: full workflow.
    resp = await client.post(
        f"/api/v1/incidents/{incident['id']}/transition", json=_transition("TRIAGED"), headers=auth(platform_token)
    )
    assert resp.status_code == 200

    # Owner: read OK, write 403.
    owner_token = await _token_for(client, db_session, org=org, level=AdminLevel.organization_admin)
    resp = await client.get(f"/api/v1/incidents/{incident['id']}", headers=auth(owner_token))
    assert resp.status_code == 200
    resp = await client.post(
        f"/api/v1/incidents/{incident['id']}/transition", json=_transition("INVESTIGATING"), headers=auth(owner_token)
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "incident_write_not_allowed"

    # Security manager: reads, cannot TRIAGE, CAN escalate.
    sm_token = await _token_for(client, db_session, org=org, role=UserRole.security_manager)
    resp = await client.get(f"/api/v1/incidents/{incident['id']}", headers=auth(sm_token))
    assert resp.status_code == 200
    resp = await client.post(
        f"/api/v1/incidents/{incident['id']}/transition", json=_transition("INVESTIGATING"), headers=auth(sm_token)
    )
    assert resp.status_code == 403
    resp = await client.post(
        f"/api/v1/incidents/{incident['id']}/transition", json=_transition("ESCALATED"), headers=auth(sm_token)
    )
    assert resp.status_code == 200

    # Unassigned platform SOC analyst: 404 (existence never leaked).
    other_token = await _token_for(client, db_session, level=AdminLevel.platform_soc_analyst)
    resp = await client.get(f"/api/v1/incidents/{incident['id']}", headers=auth(other_token))
    assert resp.status_code == 404


async def test_in_house_org_routing(db_session, client):
    """In-house org: own soc_analyst writes; a soc_analyst of ANOTHER
    in-house org gets 404; auditor (no incidents module) is 403."""
    org_a = await make_organization(db_session, soc_mode=SocMode.in_house, name="A")
    org_b = await make_organization(db_session, soc_mode=SocMode.in_house, name="B")

    token_a = await _token_for(client, db_session, org=org_a, role=UserRole.soc_analyst)
    incident = await _create_incident(client, token_a, org=org_a)

    token_b = await _token_for(client, db_session, org=org_b, role=UserRole.soc_analyst)
    resp = await client.get(f"/api/v1/incidents/{incident['id']}", headers=auth(token_b))
    assert resp.status_code == 404
    resp = await client.post(
        f"/api/v1/incidents/{incident['id']}/transition", json=_transition("TRIAGED"), headers=auth(token_b)
    )
    assert resp.status_code == 404

    auditor_token = await _token_for(client, db_session, org=org_a, role=UserRole.auditor)
    resp = await client.get("/api/v1/incidents", headers=auth(auditor_token))
    assert resp.status_code == 403  # module gate: auditor has no incidents module


# ---------------------------------------------------------------------------
# Visibility, filters, isolation.
# ---------------------------------------------------------------------------


async def test_list_filters_and_organization_scope(db_session, client):
    org_a = await make_organization(db_session, soc_mode=SocMode.in_house, name="A")
    org_b = await make_organization(db_session, soc_mode=SocMode.in_house, name="B")

    token_a = await _token_for(client, db_session, org=org_a, role=UserRole.soc_analyst)
    await _create_incident(client, token_a, org=org_a, title="A-1")
    await _create_incident(client, token_a, org=org_a, title="A-2")
    token_b = await _token_for(client, db_session, org=org_b, role=UserRole.soc_analyst)
    await _create_incident(client, token_b, org=org_b, title="B-1")

    resp = await client.get("/api/v1/incidents", headers=auth(token_a))
    assert resp.status_code == 200
    titles = {i["title"] for i in resp.json()["incidents"]}
    assert titles == {"A-1", "A-2"}  # never B's

    # Status filter.
    resp = await client.get("/api/v1/incidents?status=NEW", headers=auth(token_a))
    assert all(i["status"] == "NEW" for i in resp.json()["incidents"])

    # super_admin sees everything; organization filter scopes down.
    sa_token = await _token_for(client, db_session, level=AdminLevel.super_admin)
    resp = await client.get("/api/v1/incidents", headers=auth(sa_token))
    assert {i["title"] for i in resp.json()["incidents"]} == {"A-1", "A-2", "B-1"}
    resp = await client.get(f"/api/v1/incidents?organization_id={org_b.id}", headers=auth(sa_token))
    assert {i["title"] for i in resp.json()["incidents"]} == {"B-1"}

    # An id the caller cannot see is 404 for platform roles too.
    psa_token = await _token_for(client, db_session, level=AdminLevel.platform_soc_analyst)
    resp = await client.get(f"/api/v1/incidents?organization_id={org_a.id}", headers=auth(psa_token))
    assert resp.status_code == 404

    # Severity + assignee=me + pagination shape.
    resp = await client.get("/api/v1/incidents?severity=medium&assignee=me&limit=1", headers=auth(token_a))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["incidents"]) <= 1 and "next_cursor" in body


# ---------------------------------------------------------------------------
# PATCH, links, merge, comments.
# ---------------------------------------------------------------------------


async def test_patch_fields_and_assignee_scope(db_session, client):
    org = await make_organization(db_session, soc_mode=SocMode.in_house)
    token = await _token_for(client, db_session, org=org, role=UserRole.soc_analyst)
    incident = await _incident_for(client, db_session, org, token)

    # Unknown account id (assignee outside this organization): 404.
    resp = await client.patch(
        f"/api/v1/incidents/{incident['id']}",
        json={"assigned_account_type": "user", "assigned_account_id": str(uuid.uuid4())},
        headers=auth(token),
    )
    assert resp.status_code == 404  # existence never leaked

    analyst2 = await make_user(db_session, email=f"u2-{uuid.uuid4().hex[:8]}@x.io", role=UserRole.soc_analyst, organization_id=org.id)
    resp = await client.patch(
        f"/api/v1/incidents/{incident['id']}",
        json={"assigned_account_type": "user", "assigned_account_id": str(analyst2.id)},
        headers=auth(token),
    )
    assert resp.status_code == 200
    detail = await client.get(f"/api/v1/incidents/{incident['id']}", headers=auth(token))
    assert detail.json()["incident"]["assigned_account_id"] == str(analyst2.id)

    # Owner cannot PATCH (read-only).
    owner_token = await _token_for(client, db_session, org=org, level=AdminLevel.organization_admin)
    resp = await client.patch(f"/api/v1/incidents/{incident['id']}", json={"title": "nope"}, headers=auth(owner_token))
    assert resp.status_code == 403


async def test_links_add_remove_and_timeline(db_session, client):
    org = await make_organization(db_session, soc_mode=SocMode.in_house)
    token = await _token_for(client, db_session, org=org, role=UserRole.soc_analyst)
    alert = await _make_alert(db_session, org)
    incident = await _incident_for(client, db_session, org, token)

    resp = await client.post(
        f"/api/v1/incidents/{incident['id']}/links",
        json={"action": "add", "alert_id": str(alert.id)},
        headers=auth(token),
    )
    assert resp.status_code == 200
    await db_session.refresh(alert)
    assert alert.status == AlertStatus.triaged  # linking follows the same rule

    resp = await client.post(
        f"/api/v1/incidents/{incident['id']}/links",
        json={"action": "remove", "alert_id": str(alert.id)},
        headers=auth(token),
    )
    assert resp.status_code == 200

    # Exactly-one-target rule.
    resp = await client.post(
        f"/api/v1/incidents/{incident['id']}/links",
        json={"action": "add", "alert_id": str(alert.id), "event_id": str(uuid.uuid4())},
        headers=auth(token),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "link_target_required"

    detail = await client.get(f"/api/v1/incidents/{incident['id']}", headers=auth(token))
    entry_types = [t["entry_type"] for t in detail.json()["timeline"]]
    assert "link_change" in entry_types


async def test_merge_moves_links_and_marks_duplicate(db_session, client):
    org = await make_organization(db_session, soc_mode=SocMode.in_house)
    token = await _token_for(client, db_session, org=org, role=UserRole.soc_analyst)
    alert = await _make_alert(db_session, org)

    parent = await _incident_for(client, db_session, org, token)
    duplicate = await _create_incident(client, token, org=org, title="dup")

    # Link the alert to the duplicate.
    await client.post(
        f"/api/v1/incidents/{duplicate['id']}/links", json={"action": "add", "alert_id": str(alert.id)}, headers=auth(token)
    )

    resp = await client.post(
        f"/api/v1/incidents/{parent['id']}/merge",
        json={"duplicate_incident_id": duplicate["id"]},
        headers=auth(token),
    )
    assert resp.status_code == 200, resp.text

    await db_session.refresh(duplicate := await db_session.get(Incident, uuid.UUID(duplicate["id"])))
    assert duplicate.status == IncidentStatus.duplicate
    assert str(duplicate.duplicate_of_id) == parent["id"] and duplicate.closure_reason

    detail = await client.get(f"/api/v1/incidents/{parent['id']}", headers=auth(token))
    assert {a["id"] for a in detail.json()["alerts"]} == {str(alert.id)}  # link moved

    # Merging an already-duplicate incident again is 409.
    resp = await client.post(
        f"/api/v1/incidents/{parent['id']}/merge",
        json={"duplicate_incident_id": str(duplicate.id)},
        headers=auth(token),
    )
    assert resp.status_code == 409


async def test_comments_internal_vs_shared(db_session, client):
    org = await make_organization(db_session, soc_mode=SocMode.in_house)
    token = await _token_for(client, db_session, org=org, role=UserRole.soc_analyst)
    incident = await _incident_for(client, db_session, org, token)

    resp = await client.post(
        f"/api/v1/incidents/{incident['id']}/comments",
        json={"body": "internal note", "visibility": "internal"},
        headers=auth(token),
    )
    assert resp.status_code == 200
    resp = await client.post(
        f"/api/v1/incidents/{incident['id']}/comments",
        json={"body": "shared with the organization", "visibility": "shared"},
        headers=auth(token),
    )
    assert resp.status_code == 200

    detail = await client.get(f"/api/v1/incidents/{incident['id']}", headers=auth(token))
    comments = [t for t in detail.json()["timeline"] if t["entry_type"] == "comment"]
    assert len(comments) == 2
    assert {c["visibility"] for c in comments} == {"internal", "shared"}

    # Bad visibility value is a 422.
    resp = await client.post(
        f"/api/v1/incidents/{incident['id']}/comments",
        json={"body": "x", "visibility": "public"},
        headers=auth(token),
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Timeline + audit + side effects.
# ---------------------------------------------------------------------------


async def test_every_transition_writes_timeline_and_audit(db_session, client):
    org = await make_organization(db_session, soc_mode=SocMode.in_house)
    token = await _token_for(client, db_session, org=org, role=UserRole.soc_analyst)
    incident = await _incident_for(client, db_session, org, token)
    iid = uuid.UUID(incident["id"])

    await client.post(f"/api/v1/incidents/{iid}/transition", json=_transition("TRIAGED"), headers=auth(token))
    await client.post(f"/api/v1/incidents/{iid}/transition", json=_transition("INVESTIGATING"), headers=auth(token))

    timeline = (
        (await db_session.execute(select(IncidentTimeline).where(IncidentTimeline.incident_id == iid).order_by(IncidentTimeline.occurred_at)))
        .scalars()
        .all()
    )
    entry_types = [t.entry_type for t in timeline]
    assert entry_types[0] == "created"
    assert entry_types.count("status_change") == 2
    actor_types = {t.actor_type.value for t in timeline}
    assert actor_types == {"user"}

    audits = (
        (await db_session.execute(select(AuditLog).where(AuditLog.target_type == "incident", AuditLog.target_id == iid)))
        .scalars()
        .all()
    )
    actions = {a.action for a in audits}
    assert {"incident.create", "incident.transition"} <= actions


async def test_alert_becomes_converted_when_incident_resolved(db_session, client):
    org = await make_organization(db_session, soc_mode=SocMode.in_house)
    token = await _token_for(client, db_session, org=org, role=UserRole.soc_analyst)
    alert = await _make_alert(db_session, org)

    body = await client.post(
        "/api/v1/incidents/from-alerts", json={"alert_ids": [str(alert.id)]}, headers=auth(token)
    )
    assert body.status_code == 201
    iid = body.json()["id"]

    for status in ("TRIAGED", "INVESTIGATING", "CONTAINMENT", "REMEDIATION", "VERIFICATION", "RESOLVED"):
        resp = await client.post(f"/api/v1/incidents/{iid}/transition", json=_transition(status), headers=auth(token))
        assert resp.status_code == 200, (status, resp.text)

    await db_session.refresh(alert)
    assert alert.status == AlertStatus.converted

    # FALSE_POSITIVE path dismisses the linked alerts with the closure
    # reason, and records the side effect in the alert's own history.
    from app.models import AlertHistory

    alert2 = await _make_alert(db_session, org, rule_name="FP rule")
    body2 = await client.post(
        "/api/v1/incidents/from-alerts", json={"alert_ids": [str(alert2.id)]}, headers=auth(token)
    )
    iid2 = body2.json()["id"]
    await client.post(f"/api/v1/incidents/{iid2}/transition", json=_transition("FALSE_POSITIVE", reason="noise"), headers=auth(token))
    await db_session.refresh(alert2)
    assert alert2.status == AlertStatus.dismissed
    assert alert2.dismissed_reason == "noise"
    history = (
        (await db_session.execute(select(AlertHistory).where(AlertHistory.alert_id == alert2.id)))
        .scalars()
        .all()
    )
    dismiss_rows = [h for h in history if h.action == "dismiss" and (h.detail or {}).get("via") == "incident_transition"]
    assert len(dismiss_rows) == 1
    assert dismiss_rows[0].status_from == AlertStatus.triaged
    assert dismiss_rows[0].status_to == AlertStatus.dismissed


async def test_false_positive_allowed_from_verification(db_session, client):
    """FALSE_POSITIVE/DUPLICATE are reachable from every ACTIVE state,
    including VERIFICATION (an incident can fail verification)."""
    org = await make_organization(db_session, soc_mode=SocMode.in_house)
    token = await _token_for(client, db_session, org=org, role=UserRole.soc_analyst)
    body = await _incident_for(client, db_session, org, token)
    iid = body["id"]

    for status in ("TRIAGED", "INVESTIGATING", "CONTAINMENT", "REMEDIATION", "VERIFICATION"):
        resp = await client.post(f"/api/v1/incidents/{iid}/transition", json=_transition(status), headers=auth(token))
        assert resp.status_code == 200, (status, resp.text)

    resp = await client.post(
        f"/api/v1/incidents/{iid}/transition", json=_transition("FALSE_POSITIVE", reason="failed verification"), headers=auth(token)
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "FALSE_POSITIVE"


async def test_it_developer_sees_shared_only(db_session, client):
    """The IT developer's narrow window: their own organization's
    incidents READ-ONLY, shared timeline entries only -- and no write at
    all (create/transition/patch/links/comments are all refused)."""
    org = await make_organization(db_session, soc_mode=SocMode.in_house)
    token = await _token_for(client, db_session, org=org, role=UserRole.soc_analyst)
    incident = await _incident_for(client, db_session, org, token)

    await client.post(
        f"/api/v1/incidents/{incident['id']}/comments",
        json={"body": "SOC-only note", "visibility": "internal"},
        headers=auth(token),
    )
    await client.post(
        f"/api/v1/incidents/{incident['id']}/comments",
        json={"body": "remediation context for IT", "visibility": "shared"},
        headers=auth(token),
    )

    it_token = await _token_for(client, db_session, org=org, role=UserRole.it_developer)

    # List + detail read-only, but internal comments never leave the API.
    resp = await client.get("/api/v1/incidents", headers=auth(it_token))
    assert resp.status_code == 200
    assert {i["id"] for i in resp.json()["incidents"]} == {incident["id"]}

    resp = await client.get(f"/api/v1/incidents/{incident['id']}", headers=auth(it_token))
    assert resp.status_code == 200
    comments = [t for t in resp.json()["timeline"] if t["entry_type"] == "comment"]
    assert {c["description"] for c in comments} == {"remediation context for IT"}
    assert all(c["visibility"] == "shared" for c in comments)

    # Cross-org isolation: another org's id is 404.
    other = await make_organization(db_session, soc_mode=SocMode.in_house, name="Other")
    other_token = await _token_for(client, db_session, org=other, role=UserRole.it_developer)
    resp = await client.get(f"/api/v1/incidents/{incident['id']}", headers=auth(other_token))
    assert resp.status_code == 404

    # Every write is refused.
    resp = await client.post("/api/v1/incidents", json={"title": "x"}, headers=auth(it_token))
    assert resp.status_code == 403
    resp = await client.post(f"/api/v1/incidents/{incident['id']}/transition", json=_transition("TRIAGED"), headers=auth(it_token))
    assert resp.status_code == 403
    resp = await client.patch(f"/api/v1/incidents/{incident['id']}", json={"title": "nope"}, headers=auth(it_token))
    assert resp.status_code == 403
    resp = await client.post(
        f"/api/v1/incidents/{incident['id']}/links", json={"action": "add", "alert_id": str(uuid.uuid4())}, headers=auth(it_token)
    )
    assert resp.status_code == 403
    resp = await client.post(
        f"/api/v1/incidents/{incident['id']}/comments", json={"body": "x"}, headers=auth(it_token)
    )
    assert resp.status_code == 403
    resp = await client.post(
        f"/api/v1/incidents/{incident['id']}/merge", json={"duplicate_incident_id": str(uuid.uuid4())}, headers=auth(it_token)
    )
    assert resp.status_code == 403
