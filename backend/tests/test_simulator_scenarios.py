"""
Simulator scenario generators (tools/simulator, P08): real counts and
types per scenario for a given seed, the sim_scenario marker inside
every raw payload, determinism, and no real personal data.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

# tools/ lives at the repo root, outside backend/ where pytest runs --
# put the repo root on sys.path so `import tools.simulator` resolves.
REPO_ROOT = str(Path(__file__).resolve().parents[2])
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tools.simulator.scenarios import SCENARIOS, generate  # noqa: E402

BASE = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)

# Each scenario's contract: exact event count + the event types that
# must appear (the "story" the scenario is supposed to tell).
EXPECTED: dict[str, tuple[int, set[str]]] = {
    "ssh_or_windows_bruteforce": (22, {"logon_failure", "logon_success", "process_create"}),
    "privilege_escalation": (6, {"sudo_command", "group_change", "permission_change"}),
    "new_user_created": (3, {"user_add", "account_created", "app_login"}),
    "service_installed": (2, {"service_install", "process_create"}),
    "audit_log_cleared": (2, {"log_cleared"}),
    "suspicious_download": (3, {"process_create", "app_warning"}),
    "benign_noise": (12, {"auth_success"}),
    "mixed": (34, {"auth_success", "logon_failure", "logon_success"}),
}


def test_all_scenarios_present():
    assert set(EXPECTED) == set(SCENARIOS)


def test_counts_and_story_types():
    for name, (count, types) in EXPECTED.items():
        events = generate(name, seed=7, base_time=BASE)
        assert len(events) == count, f"{name}: expected {count} events, got {len(events)}"
        produced = {e["event_type"] for e in events}
        assert types <= produced, f"{name}: missing story types {types - produced}"


def test_every_event_carries_scenario_marker_in_raw():
    for name in SCENARIOS:
        for event in generate(name, seed=3, base_time=BASE):
            # `mixed` composes the two sub-scenarios, which keep their own
            # markers -- both must be within the composed scenario's set.
            expected = {name} if name != "mixed" else {"benign_noise", "ssh_or_windows_bruteforce"}
            assert event["raw"]["sim"]["scenario"] in expected, (name, event["raw"])


def test_same_seed_same_events():
    a = generate("mixed", seed=123, base_time=BASE)
    b = generate("mixed", seed=123, base_time=BASE)
    assert a == b


def test_different_seed_changes_content():
    a = generate("benign_noise", seed=1, base_time=BASE)
    b = generate("benign_noise", seed=2, base_time=BASE)
    assert a != b  # different draws -- e.g. different hosts/users/hashes


def test_schema_fields_valid_for_ingestion():
    """Everything the P07 API rejects must already be right here."""
    from tools.simulator.scenarios import SCHEMA_VERSION

    for name in SCENARIOS:
        for event in generate(name, seed=11, base_time=BASE):
            assert event["schema_version"] == SCHEMA_VERSION
            for field in ("timestamp", "source_type", "event_type", "message"):
                assert isinstance(event[field], str) and event[field].strip(), (name, field)
            assert event["severity_hint"] in (None, "critical", "high", "medium", "low", "info")
            # Raw payloads must be JSON objects (the API keeps them verbatim).
            assert isinstance(event["raw"], dict)


def test_bruteforce_story_order():
    """The bruteforce narrative is ordered: 20 failures, then success,
    then the privileged command."""
    events = generate("ssh_or_windows_bruteforce", seed=5, base_time=BASE)
    kinds = [e["event_type"] for e in events]
    assert kinds[:20] == ["logon_failure"] * 20
    assert kinds[20] == "logon_success"
    assert kinds[21] == "process_create"
    timestamps = [e["timestamp"] for e in events]
    assert timestamps == sorted(timestamps)  # chronological


def test_no_real_personal_data():
    """IPs come from documentation/private ranges; users are the fixed
    synthetic list; hosts are lab hostnames."""
    allowed_prefixes = ("10.", "192.0.2.", "198.51.100.", "203.0.113.")
    allowed_users = {
        "alice.analyst", "bob.dev", "svc.backup", "svc.build", "carol.manager",
        "SYSTEM", "root",
    }
    for name in SCENARIOS:
        for event in generate(name, seed=99, base_time=BASE):
            if event.get("ip"):
                assert event["ip"].startswith(allowed_prefixes), (name, event["ip"])
            if event.get("user"):
                assert event["user"] in allowed_users or event["user"].startswith("svc."), (name, event["user"])
            if event.get("host"):
                assert event["host"].startswith("lab-"), (name, event["host"])


def test_unknown_scenario_raises():
    try:
        generate("no_such_scenario", seed=1)
    except KeyError as exc:
        assert "no_such_scenario" in str(exc)
    else:
        raise AssertionError("expected KeyError for unknown scenario")
