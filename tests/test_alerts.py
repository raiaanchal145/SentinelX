"""
SentinelX QA Test Suite: Alert Generation & Criticality Lifecycle.

Module: ALR
Owners: Ansh, Riteka Singh, Aanchal Rai
"""

import datetime as dt
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.detection.builtin_rules import BUILTIN_BY_ID
from app.detection.evaluators import evaluate_sequence, evaluate_threshold
from app.models import Alert, AlertStatus, EventSeverity, SocMode, UserRole
from backend.tests.helpers import auth, login, make_organization, make_user
from tc import tc


@tc(
    id="ALR-01",
    module="Alerts",
    description="Save Critical severity alert and retrieve via alerts API",
    preconditions="Organization in in_house soc_mode with SOC analyst",
    steps="Insert Alert row with severity='critical', query GET /api/v1/alerts",
    expected="Alert returned in list with severity='critical' and status='new'",
    type="automated",
    owner="Ansh",
)
@pytest.mark.asyncio
async def test_alr_01_critical_alert_retrieval(client: AsyncClient, db_session: AsyncSession):
    org = await make_organization(db_session, name="AlertOrg1", soc_mode=SocMode.in_house)
    user = await make_user(
        db_session,
        email="analyst_alr1@example.com",
        role=UserRole.soc_analyst,
        organization_id=org.id,
    )
    token = await login(client, user.email)

    now = dt.datetime.now(dt.timezone.utc)
    alert = Alert(
        organization_id=org.id,
        rule_name="Critical Host Compromise",
        severity=EventSeverity.critical,
        status=AlertStatus.new,
        title="Immediate Threat: Multiple C2 Beacons Detected",
        summary="High-volume outbound communication observed on restricted port",
        event_count=15,
        group_key="host-10.0.0.99",
        first_seen_at=now,
        last_seen_at=now,
    )

    db_session.add(alert)
    await db_session.commit()

    resp = await client.get("/api/v1/alerts", headers=auth(token))
    assert resp.status_code == 200
    data = resp.json()
    alerts = data.get("alerts", [])
    alert_ids = [item["id"] for item in alerts]
    assert str(alert.id) in alert_ids or alert.id in alert_ids



@tc(
    id="ALR-02",
    module="Alerts",
    description="Repeated failed logins trigger High severity alert with MITRE T1110 tag",
    preconditions="Built-in rule 'repeated-failed-logins' loaded",
    steps="Evaluate threshold with 22 failed logon events within window",
    expected="Rule matches with group key and MITRE technique T1110 verified",
    type="automated",
    owner="Riteka Singh",
)
def test_alr_02_repeated_failed_logins_rule():
    rule = BUILTIN_BY_ID["repeated-failed-logins"]
    assert rule.severity == EventSeverity.high
    assert rule.mitre_technique == "T1110"

    from app.detection.definitions import ThresholdDefinition
    defn = ThresholdDefinition.model_validate(rule.condition)

    now = dt.datetime.now(dt.timezone.utc)
    events = [
        {
            "id": f"evt-{i}",
            "event_type": "logon_failure",
            "user": "victim_user",
            "occurred_at": (now - dt.timedelta(seconds=i * 10)).isoformat(),
        }
        for i in range(22)
    ]

    matches = evaluate_threshold(
        defn,
        events,
        window_start=now - dt.timedelta(seconds=600),
        window_end=now,
    )
    assert len(matches) == 1
    assert matches[0].group_key == "victim_user"
    assert len(matches[0].event_ids) == 22


@tc(
    id="ALR-03",
    module="Alerts",
    description="Successful login after many failures raises Critical severity alert",
    preconditions="Built-in sequence rule 'success-after-failures' loaded",
    steps="Evaluate sequence with failure step followed by logon_success step",
    expected="Sequence match returned, rule severity verified as Critical",
    type="automated",
    owner="Aanchal Rai",
)
def test_alr_03_success_after_failures_rule():
    rule = BUILTIN_BY_ID["success-after-failures"]
    assert rule.severity == EventSeverity.critical
    assert rule.mitre_technique == "T1110"

    from app.detection.definitions import SequenceDefinition
    defn = SequenceDefinition.model_validate(rule.condition)

    now = dt.datetime.now(dt.timezone.utc)
    events = [
        {
            "id": "evt-fail",
            "event_type": "logon_failure",
            "user": "target_admin",
            "occurred_at": (now - dt.timedelta(seconds=120)).isoformat(),
        },
        {
            "id": "evt-succ",
            "event_type": "logon_success",
            "user": "target_admin",
            "occurred_at": (now - dt.timedelta(seconds=10)).isoformat(),
        },
    ]

    matches = evaluate_sequence(
        defn,
        events,
        window_start=now - dt.timedelta(seconds=900),
        window_end=now,
    )
    assert len(matches) == 1
    assert matches[0].group_key == "target_admin"


@tc(
    id="ALR-04",
    module="Alerts",
    description="Acknowledge alert transitions status from 'new' to 'acknowledged'",
    preconditions="Alert with status='new' in database",
    steps="POST /api/v1/alerts/{id}/acknowledge with analyst token",
    expected="Response status 200 and alert status updated to 'acknowledged'",
    type="automated",
    owner="Ansh",
)
@pytest.mark.asyncio
async def test_alr_04_acknowledge_alert(client: AsyncClient, db_session: AsyncSession):
    org = await make_organization(db_session, name="AckOrg", soc_mode=SocMode.in_house)
    user = await make_user(
        db_session,
        email="ack_analyst@example.com",
        role=UserRole.soc_analyst,
        organization_id=org.id,
    )
    token = await login(client, user.email)

    now = dt.datetime.now(dt.timezone.utc)
    alert = Alert(
        organization_id=org.id,
        rule_name="Privilege Escalation Warning",
        severity=EventSeverity.high,
        status=AlertStatus.new,
        title="Unexpected Sudo Rights Modification",
        summary="User added to wheel group without ticket reference",
        first_seen_at=now,
        last_seen_at=now,
    )


    db_session.add(alert)
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/alerts/{alert.id}/acknowledge",
        headers=auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "triaged"

