"""
Detection evaluator unit tests (P23) -- pure functions, no DB, no
Redis. Covers every built-in rule's definition shape plus the window
edge cases the brief names: an event exactly at the window boundary,
out-of-order arrival, and two users' events interleaved.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.detection.definitions import (
    PatternCondition,
    PatternDefinition,
    SequenceDefinition,
    SequenceStep,
    ThresholdDefinition,
    parse_definition,
)
from app.detection.evaluators import evaluate

NOW = datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc)
WINDOW = 600  # seconds


def _event(event_type, user="alice", ip="10.0.0.1", host="lab-win01", minutes_ago=0, **extra):
    event = {
        "id": str(uuid.uuid4()),
        "event_type": event_type,
        "username": user,
        "source_ip": ip,
        "host": host,
        "occurred_at": NOW - timedelta(minutes=minutes_ago),
        "raw": extra.pop("raw", {}),
        "normalized": {},
    }
    event.update(extra)
    return event


# ---------------------------------------------------------------------------
# threshold
# ---------------------------------------------------------------------------


def _threshold(threshold=3, window_seconds=WINDOW, types=("logon_failure",)):
    return ThresholdDefinition(
        event_types=list(types), threshold=threshold, window_seconds=window_seconds, group_by="user"
    )


def test_threshold_positive():
    events = [_event("logon_failure", minutes_ago=5 - i) for i in range(3)]
    matches = evaluate("threshold", _threshold(3), events, window_start=NOW - timedelta(seconds=WINDOW), window_end=NOW)
    assert len(matches) == 1
    assert matches[0].group_key == "alice"
    assert len(matches[0].event_ids) == 3


def test_threshold_negative_below_count():
    events = [_event("logon_failure", minutes_ago=5 - i) for i in range(2)]
    matches = evaluate("threshold", _threshold(3), events, window_start=NOW - timedelta(seconds=WINDOW), window_end=NOW)
    assert matches == []


def test_threshold_event_exactly_at_boundary_counts():
    """The boundary event (occurred exactly window_start ago) is IN the
    window -- sliding windows are inclusive of their left edge."""
    boundary = NOW - timedelta(seconds=WINDOW)
    events = [
        {**_event("logon_failure", minutes_ago=1), "occurred_at": NOW - timedelta(seconds=30)},
        {**_event("logon_failure", minutes_ago=1), "occurred_at": boundary},
    ]
    matches = evaluate("threshold", _threshold(2), events, window_start=boundary, window_end=NOW)
    assert len(matches) == 1  # the boundary event counts


def test_threshold_outside_window_does_not_count():
    events = [
        {**_event("logon_failure"), "occurred_at": NOW - timedelta(seconds=WINDOW + 1)},
        {**_event("logon_failure"), "occurred_at": NOW - timedelta(seconds=30)},
    ]
    matches = evaluate("threshold", _threshold(2), events, window_start=NOW - timedelta(seconds=WINDOW), window_end=NOW)
    assert matches == []


def test_threshold_interleaved_users_are_separate_groups():
    events = []
    for i in range(3):
        events.append(_event("logon_failure", user="alice", minutes_ago=2))
        events.append(_event("logon_failure", user="bob", minutes_ago=1))
    matches = evaluate("threshold", _threshold(3), events, window_start=NOW - timedelta(seconds=WINDOW), window_end=NOW)
    keys = sorted(m.group_key for m in matches)
    assert keys == ["alice", "bob"]  # two independent hits, no cross-contamination
    for match in matches:
        assert len(match.event_ids) == 3


def test_threshold_out_of_order_events_still_count():
    """Arrival order doesn't matter -- the evaluator sorts by time."""
    events = [
        _event("logon_failure", minutes_ago=1),
        _event("logon_failure", minutes_ago=5),
        _event("logon_failure", minutes_ago=3),
    ]
    matches = evaluate("threshold", _threshold(3), events, window_start=NOW - timedelta(seconds=WINDOW), window_end=NOW)
    assert len(matches) == 1
    ids = matches[0].event_ids
    assert len(ids) == 3


def test_threshold_group_by_ip():
    definition = ThresholdDefinition(
        event_types=["firewall_deny"], threshold=3, window_seconds=WINDOW, group_by="ip"
    )
    events = [_event("firewall_deny", ip="203.0.113.9", minutes_ago=i) for i in range(3)]
    events += [_event("firewall_deny", ip="198.51.100.7", minutes_ago=i) for i in range(3)]
    matches = evaluate("threshold", definition, events, window_start=NOW - timedelta(seconds=WINDOW), window_end=NOW)
    keys = sorted(m.group_key for m in matches)
    assert keys == ["198.51.100.7", "203.0.113.9"]  # both IPs crossed 3


# ---------------------------------------------------------------------------
# sequence
# ---------------------------------------------------------------------------


def _sequence():
    return SequenceDefinition(
        steps=[SequenceStep(event_type="logon_failure"), SequenceStep(event_type="logon_success")],
        window_seconds=900,
        group_by="user",
    )


def test_sequence_positive_in_order():
    events = [
        _event("logon_failure", minutes_ago=10),
        _event("logon_success", minutes_ago=5),
    ]
    matches = evaluate("sequence", _sequence(), events, window_start=NOW - timedelta(seconds=900), window_end=NOW)
    assert len(matches) == 1
    assert matches[0].group_key == "alice"
    assert len(matches[0].event_ids) == 2


def test_sequence_negative_wrong_order():
    events = [
        _event("logon_success", minutes_ago=10),  # success FIRST
        _event("logon_failure", minutes_ago=5),
    ]
    matches = evaluate("sequence", _sequence(), events, window_start=NOW - timedelta(seconds=900), window_end=NOW)
    assert matches == []


def test_sequence_negative_other_user_does_not_inherit():
    """alice fails; bob succeeds -- no sequence for either."""
    events = [
        _event("logon_failure", user="alice", minutes_ago=10),
        _event("logon_success", user="bob", minutes_ago=5),
    ]
    matches = evaluate("sequence", _sequence(), events, window_start=NOW - timedelta(seconds=900), window_end=NOW)
    assert matches == []


def test_sequence_interleaved_noise_does_not_break_order():
    events = [
        _event("logon_failure", minutes_ago=10),
        _event("app_login", minutes_ago=8),  # unrelated noise between the steps
        _event("container_start", minutes_ago=7),
        _event("logon_success", minutes_ago=5),
    ]
    matches = evaluate("sequence", _sequence(), events, window_start=NOW - timedelta(seconds=900), window_end=NOW)
    assert len(matches) == 1


# ---------------------------------------------------------------------------
# pattern
# ---------------------------------------------------------------------------


def _log_cleared_pattern():
    return PatternDefinition(match=[PatternCondition(field="event_type", op="eq", value="log_cleared")])


def test_pattern_positive_and_negative():
    hit = _event("log_cleared", raw={"event_id": 1102})
    miss = _event("app_login")
    matches = evaluate("pattern", _log_cleared_pattern(), [hit, miss], window_start=NOW, window_end=NOW)
    assert len(matches) == 1
    assert matches[0].event_ids == [hit["id"]]


def test_pattern_exclude_blocklist():
    definition = PatternDefinition(
        match=[PatternCondition(field="event_type", op="eq", value="group_change")],
        exclude=[PatternCondition(field="user", op="starts_with", value="svc.")],
    )
    hit = _event("group_change", user="alice")
    allowed = _event("group_change", user="svc.backup")
    matches = evaluate("pattern", definition, [hit, allowed], window_start=NOW, window_end=NOW)
    assert [m.group_key for m in matches] == [f"event={hit['id']}"]


def test_pattern_raw_field_path():
    definition = PatternDefinition(
        match=[
            PatternCondition(field="event_type", op="eq", value="process_create"),
            PatternCondition(field="raw.process_name", op="contains", value="powershell"),
        ],
    )
    hit = _event("process_create", raw={"process_name": "powershell.exe"})
    miss = _event("process_create", raw={"process_name": "notepad.exe"})
    matches = evaluate("pattern", definition, [hit, miss], window_start=NOW, window_end=NOW)
    assert [m.event_ids[0] for m in matches] == [hit["id"]]


# ---------------------------------------------------------------------------
# the two built-in rules with no dedicated engine-test coverage
# ---------------------------------------------------------------------------


def test_builtin_suspicious_process_path_positive_and_excluded_browser():
    """suspicious-process-path: a process from a user-writable path hits;
    the allowlisted browser (msedge.exe) does not, even from Downloads."""
    from app.detection.builtin_rules import BUILTIN_BY_ID

    definition = parse_definition(
        "pattern", BUILTIN_BY_ID["suspicious-process-path"].condition
    )
    hit = _event("process_create", raw={"process_name": "C:\\Users\\bob\\AppData\\Local\\Temp\\dropper.exe"})
    browser = _event("process_create", raw={"process_name": "C:\\Users\\bob\\Downloads\\msedge.exe"})
    matches = evaluate("pattern", definition, [hit, browser], window_start=NOW, window_end=NOW)
    assert [m.event_ids[0] for m in matches] == [hit["id"]]


def test_builtin_suspicious_process_path_negative_normal_binary():
    from app.detection.builtin_rules import BUILTIN_BY_ID

    definition = parse_definition(
        "pattern", BUILTIN_BY_ID["suspicious-process-path"].condition
    )
    clean = _event("process_create", raw={"process_name": "C:\\Windows\\System32\\svchost.exe"})
    assert evaluate("pattern", definition, [clean], window_start=NOW, window_end=NOW) == []


def test_builtin_admin_login_new_ip_positive():
    """admin-login-new-ip: app_login -> sudo_command, same IP, in order."""
    from app.detection.builtin_rules import BUILTIN_BY_ID

    definition = parse_definition(
        "sequence", BUILTIN_BY_ID["admin-login-new-ip"].condition
    )
    events = [
        _event("app_login", ip="203.0.113.66", minutes_ago=10),
        _event("sudo_command", ip="203.0.113.66", minutes_ago=5),
    ]
    matches = evaluate("sequence", definition, events, window_start=NOW - timedelta(seconds=1800), window_end=NOW)
    assert len(matches) == 1
    assert matches[0].group_key == "203.0.113.66"


def test_builtin_admin_login_new_ip_negative_wrong_order_and_different_ips():
    """sudo BEFORE login is not the sequence; different IPs don't group."""
    from app.detection.builtin_rules import BUILTIN_BY_ID

    definition = parse_definition(
        "sequence", BUILTIN_BY_ID["admin-login-new-ip"].condition
    )
    wrong_order = [
        _event("sudo_command", ip="203.0.113.66", minutes_ago=10),
        _event("app_login", ip="203.0.113.66", minutes_ago=5),
    ]
    assert evaluate("sequence", definition, wrong_order, window_start=NOW - timedelta(seconds=1800), window_end=NOW) == []

    split_ips = [
        _event("app_login", ip="203.0.113.66", minutes_ago=10),
        _event("sudo_command", ip="198.51.100.24", minutes_ago=5),
    ]
    assert evaluate("sequence", definition, split_ips, window_start=NOW - timedelta(seconds=1800), window_end=NOW) == []


# ---------------------------------------------------------------------------
# definition validation
# ---------------------------------------------------------------------------


def test_parse_definition_rejects_bad_shapes():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        parse_definition("threshold", {"threshold": 1, "window_seconds": 60, "event_types": ["x"]})  # threshold < 2
    with pytest.raises(ValidationError):
        parse_definition("threshold", {"threshold": 5, "window_seconds": 10, "event_types": ["x"]})  # window < 60s
    with pytest.raises(ValidationError):
        parse_definition("sequence", {"steps": [{"event_type": "x"}], "window_seconds": 60})  # 1 step
    with pytest.raises(ValueError):
        parse_definition("statistical", {})  # no evaluator for this type yet
