"""
GET /api/v1/events/summary (the SOC Overview tile's data source) and
the optional organization_id filter on GET /events (platform SOC /
super_admin scoping the UI to one organization). Visibility rules must
match the list endpoint: unknown/unassigned organization -> 404
organization_not_found, same as the assets convention.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import EventSource, OrganizationModule, SecurityEvent

from tests.helpers import make_admin, make_organization, make_user

pytestmark = pytest.mark.asyncio

NOW = datetime.now(timezone.utc)


async def _login(client, email):
    from tests.helpers import TEST_PASSWORD

    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


async def _seed_org_with_events(db, *, name, event_count=5, soc_mode="in_house"):
    org = await make_organization(db, name=name, soc_mode=soc_mode)
    source = EventSource(organization_id=org.id, name=f"{name} src", source_type="test", status="active")
    db.add(source)
    await db.flush()
    for i in range(event_count):
        db.add(
            SecurityEvent(
                organization_id=org.id,
                event_source_id=source.id,
                occurred_at=NOW - timedelta(minutes=i),
                event_type="auth_failure" if i % 2 == 0 else "test_event",
                severity="medium" if i % 2 == 0 else "info",
                username="simuser",
                source_ip="10.0.0.1",
                dedup_hash=f"{name}-{i}",
                raw_data={"seed": name},
                normalized_data={"message": f"event {i} for {name}"},
            )
        )
    await db.commit()
    return org, source


async def _make_super_admin(db, email):
    return await make_admin(
        db,
        email=email,
        name="Super",
        admin_level="super_admin",
        organization_id=None,
    )


async def test_summary_totals_and_timeline(client, db_session):
    org, _source = await _seed_org_with_events(db_session, name="SummaryCo", event_count=5)
    admin = await _make_super_admin(db_session, "summary-super@example.com")
    token = await _login(client, admin.email)

    resp = await client.get(
        "/api/v1/events/summary",
        params={"bucket_hours": 24, "buckets": 12},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 5
    assert sum(body["timeline"]) == 5
    assert body["timeline"][-1] >= 1  # the newest event is in the last bucket
    assert body["by_severity"].get("medium") == 3
    assert body["by_type"].get("auth_failure") == 3


async def test_summary_scoped_to_one_organization(client, db_session):
    org_a, _ = await _seed_org_with_events(db_session, name="SumOrgA", event_count=3)
    org_b, _ = await _seed_org_with_events(db_session, name="SumOrgB", event_count=4)
    admin = await _make_super_admin(db_session, "summary-scope-super@example.com")
    token = await _login(client, admin.email)

    resp = await client.get(
        "/api/v1/events/summary", params={"organization_id": str(org_b.id)}, headers=_auth(token)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 4

    # super_admin with no filter sees both organizations.
    resp = await client.get("/api/v1/events/summary", headers=_auth(token))
    assert resp.json()["total"] == 7


async def test_summary_in_house_sees_only_own_org(client, db_session):
    org_a, _ = await _seed_org_with_events(db_session, name="SumHouseA", event_count=2)
    org_b, _ = await _seed_org_with_events(db_session, name="SumHouseB", event_count=9)
    user = await make_user(
        db_session,
        email="sumhouse-analyst@example.com",
        name="Analyst",
        role="soc_analyst",
        organization_id=org_a.id,
    )
    token = await _login(client, user.email)

    resp = await client.get("/api/v1/events/summary", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["total"] == 2  # own org only, never B's 9

    # An in-house account naming another (invisible) org: 404, no leak.
    resp = await client.get(
        "/api/v1/events/summary", params={"organization_id": str(org_b.id)}, headers=_auth(token)
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "organization_not_found"


async def test_list_organization_filter(client, db_session):
    org_a, _ = await _seed_org_with_events(db_session, name="ListOrgA", event_count=2)
    org_b, _ = await _seed_org_with_events(db_session, name="ListOrgB", event_count=3)
    admin = await _make_super_admin(db_session, "listfilter-super@example.com")
    token = await _login(client, admin.email)

    resp = await client.get(
        "/api/v1/events", params={"organization_id": str(org_b.id)}, headers=_auth(token)
    )
    assert resp.status_code == 200, resp.text
    orgs_seen = {e["organization_id"] for e in resp.json()["events"]}
    assert orgs_seen == {str(org_b.id)}

    # An unknown organization id: 404 organization_not_found.
    resp = await client.get(
        "/api/v1/events", params={"organization_id": "00000000-0000-0000-0000-000000000000"}, headers=_auth(token)
    )
    assert resp.status_code == 404


async def test_summary_respects_filters(client, db_session):
    org, _ = await _seed_org_with_events(db_session, name="SumFilterCo", event_count=6)
    admin = await _make_super_admin(db_session, "sumfilter-super@example.com")
    token = await _login(client, admin.email)

    resp = await client.get(
        "/api/v1/events/summary",
        params={"severity": "medium", "bucket_hours": 24},
        headers=_auth(token),
    )
    body = resp.json()
    assert body["total"] == 3  # every other seeded event is medium
    assert set(body["by_severity"]) == {"medium"}


async def test_summary_empty_for_unassigned_platform_soc(client, db_session):
    from app.models import Admin, AdminLevel, AccountEmail
    from app.security import hash_password
    from tests.helpers import TEST_PASSWORD

    await _seed_org_with_events(db_session, name="SumNoAssign", event_count=4)
    admin = Admin(
        name="Lonely SOC",
        email="sum-noassign@example.com",
        password_hash=hash_password(TEST_PASSWORD),
        admin_level=AdminLevel.platform_soc_analyst,
        organization_id=None,
        is_active=True,
        is_verified=True,
    )
    db_session.add(admin)
    await db_session.flush()
    db_session.add(AccountEmail(email=admin.email, account_type="admin", account_id=admin.id))
    await db_session.commit()

    token = await _login(client, admin.email)
    resp = await client.get("/api/v1/events/summary", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["timeline"] == [0] * body["buckets"]
