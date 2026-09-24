"""
Parser tests (P07): real sample lines for each source type, plus
malformed input. Parsers are pure functions (app/worker/parsers.py) --
these tests run with no database.
"""

import pytest

from app.worker.parsers import (
    parse_application,
    parse_custom_json,
    parse_docker,
    parse_linux_auth,
    parse_network,
    parse_record,
    parse_test,
    parse_windows,
)

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# linux_auth -- real syslog lines (OpenSSH/sshd/sudo/useradd shapes).
# ---------------------------------------------------------------------------


def _linux(record):
    return parse_linux_auth(record)


async def test_linux_auth_failed_password():
    record = {
        "source_type": "linux_auth",
        "event_type": "auth_failure",
        "message": "Sep 24 03:14:15 web01 sshd[2201]: Failed password for root from 203.0.113.9 port 41000 ssh2",
    }
    parsed = _linux(record)
    assert parsed.event_type == "auth_failure"
    assert parsed.host == "web01"
    assert parsed.process == "sshd"
    assert parsed.user == "root"
    assert parsed.ip == "203.0.113.9"


async def test_linux_auth_failed_password_invalid_user():
    record = {
        "source_type": "linux_auth",
        "event_type": "auth_failure",
        "message": "Sep 24 03:14:15 web01 sshd[2201]: Failed password for invalid user admin from 198.51.100.7 port 51022 ssh2",
    }
    parsed = _linux(record)
    assert parsed.event_type == "auth_failure"
    assert parsed.user == "admin"
    assert parsed.ip == "198.51.100.7"


async def test_linux_auth_accepted_publickey():
    record = {
        "source_type": "linux_auth",
        "event_type": "auth_success",
        "message": "Sep 24 09:00:01 db01 sshd[881]: Accepted publickey for deploy from 10.0.0.5 port 55100 ssh2: RSA SHA256:abc",
    }
    parsed = _linux(record)
    assert parsed.event_type == "auth_success"
    assert parsed.user == "deploy"
    assert parsed.ip == "10.0.0.5"


async def test_linux_auth_sudo():
    record = {
        "source_type": "linux_auth",
        "event_type": "sudo_command",
        "message": "Sep 24 10:00:00 web01 sudo:   alice : TTY=pts/0 ; PWD=/home/alice ; USER=root ; COMMAND=/usr/bin/systemctl restart nginx",
    }
    parsed = _linux(record)
    assert parsed.event_type == "sudo_command"
    assert parsed.user == "alice"
    assert parsed.process == "sudo"
    assert parsed.extracted["sudo"]["COMMAND"] == "/usr/bin/systemctl restart nginx"
    assert parsed.extracted["sudo"]["USER"] == "root"


async def test_linux_auth_useradd():
    record = {
        "source_type": "linux_auth",
        "event_type": "user_add",
        "message": "Sep 24 11:20:00 web01 useradd[3121]: new user: name=backupservice, UID=1002, GID=1002, home=/home/backupservice, shell=/bin/bash",
    }
    parsed = _linux(record)
    assert parsed.event_type == "user_add"
    assert parsed.user == "backupservice"


async def test_linux_auth_unparseable_keeps_declared_type():
    record = {
        "source_type": "linux_auth",
        "event_type": "auth_failure",
        "message": "total garbage that matches nothing at all",
    }
    parsed = _linux(record)
    assert parsed.event_type is None  # caller keeps the declared auth_failure


async def test_linux_auth_malformed_input_does_not_crash():
    for junk in ["", "   ", "::::", "[[[[[", "Sep 99 99:99:99", None]:
        parsed = parse_record("linux_auth", {"source_type": "linux_auth", "event_type": "other", "message": junk or ""})
        assert parsed is not None


# ---------------------------------------------------------------------------
# application -- JSON (raw object), logfmt, bracketed formats.
# ---------------------------------------------------------------------------


async def test_application_json_error():
    record = {
        "source_type": "application",
        "event_type": "api_error",
        "message": "payment timeout",
        "raw": {"level": "error", "message": "Payment gateway timeout", "user": "alice", "service": "billing"},
    }
    parsed = parse_application(record)
    assert parsed.event_type == "app_error"
    assert parsed.user == "alice"
    assert parsed.process == "billing"


async def test_application_logfmt():
    record = {
        "source_type": "application",
        "event_type": "app_warning",
        "message": 'level=warn msg="slow query" service=api ip=10.1.2.3',
    }
    parsed = parse_application(record)
    assert parsed.event_type == "app_warning"
    assert parsed.ip == "10.1.2.3"
    assert parsed.process == "api"


async def test_application_bracketed():
    record = {
        "source_type": "application",
        "event_type": "app_error",
        "message": "2026-09-24 10:11:12 ERROR [billing] Payment gateway timeout",
    }
    parsed = parse_application(record)
    assert parsed.event_type == "app_error"
    assert parsed.process == "billing"
    assert "Payment gateway timeout" in parsed.extracted["detail"]


async def test_application_malformed_keeps_declared():
    record = {"source_type": "application", "event_type": "app_login", "message": "level====broken==="}
    parsed = parse_application(record)
    assert parsed.event_type is None  # caller keeps app_login


# ---------------------------------------------------------------------------
# docker -- daemon JSON events and plain lines.
# ---------------------------------------------------------------------------


async def test_docker_container_start():
    record = {
        "source_type": "docker",
        "event_type": "container_start",
        "message": "container start",
        "raw": {
            "status": "start",
            "id": "abc123def",
            "from": "nginx:latest",
            "Actor": {"ID": "abc123def", "Attributes": {"name": "web-proxy", "image": "nginx:latest", "host": "docker01"}},
        },
    }
    parsed = parse_docker(record)
    assert parsed.event_type == "container_start"
    assert parsed.process == "web-proxy"
    assert parsed.host == "docker01"
    assert parsed.extracted["image"] == "nginx:latest"


async def test_docker_oom_kill():
    record = {
        "source_type": "docker",
        "event_type": "container_kill",
        "message": "container killed",
        "raw": {"status": "oom", "id": "deadbeef", "Actor": {"Attributes": {"name": "worker"}}},
    }
    parsed = parse_docker(record)
    assert parsed.event_type == "container_kill"


async def test_docker_plain_line():
    record = {
        "source_type": "docker",
        "event_type": "container_stop",
        "message": "container abc123: stop nginx:latest",
    }
    parsed = parse_docker(record)
    assert parsed.event_type == "container_stop"
    assert parsed.process == "abc123"


async def test_docker_unknown_status_maps_to_other():
    record = {
        "source_type": "docker",
        "event_type": "container_start",
        "message": "container xyz: prune",
        "raw": {"status": "prune", "id": "xyz"},
    }
    parsed = parse_docker(record)
    assert parsed.event_type == "other"  # unmappable verb -> other, raw kept


# ---------------------------------------------------------------------------
# network -- iptables kernel lines and JSON flow records.
# ---------------------------------------------------------------------------


async def test_network_iptables_deny():
    record = {
        "source_type": "network",
        "event_type": "firewall_deny",
        "message": "iptables DENY IN=eth0 SRC=203.0.113.9 DST=10.0.0.5 PROTO=TCP DPT=22",
    }
    parsed = parse_network(record)
    assert parsed.event_type == "firewall_deny"
    assert parsed.ip == "203.0.113.9"
    assert parsed.extracted["dst_ip"] == "10.0.0.5"
    assert parsed.extracted["dst_port"] == "22"


async def test_network_json_flow_blocked():
    record = {
        "source_type": "network",
        "event_type": "connection_blocked",
        "message": "flow",
        "raw": {"action": "blocked", "src_ip": "198.51.100.7", "dst_ip": "10.0.0.5", "dst_port": 3389, "proto": "TCP", "device": "fw-edge-1"},
    }
    parsed = parse_network(record)
    assert parsed.event_type == "connection_blocked"
    assert parsed.ip == "198.51.100.7"
    assert parsed.extracted["dst_port"] == 3389


async def test_network_port_scan_detected():
    record = {
        "source_type": "network",
        "event_type": "port_scan",
        "message": "scan",
        "raw": {"scan_detected": True, "src_ip": "203.0.113.66"},
    }
    parsed = parse_network(record)
    assert parsed.event_type == "port_scan"


async def test_network_malformed():
    parsed = parse_network({"source_type": "network", "event_type": "other", "message": "no fields here"})
    assert parsed.event_type is None


# ---------------------------------------------------------------------------
# windows -- the P21 agent's JSON shape and the text fallback.
# ---------------------------------------------------------------------------


async def test_windows_logon_failure_4625():
    record = {
        "source_type": "windows",
        "event_type": "logon_failure",
        "message": "logon failed",
        "raw": {"event_id": 4625, "host": "WS-042", "user": "alice", "ip": "10.0.0.8", "log_name": "Security"},
    }
    parsed = parse_windows(record)
    assert parsed.event_type == "logon_failure"
    assert parsed.host == "WS-042"
    assert parsed.user == "alice"


async def test_windows_process_create_4688():
    record = {
        "source_type": "windows",
        "event_type": "process_create",
        "message": "process created",
        "raw": {"event_id": 4688, "process_name": "powershell.exe", "computer": "WS-042"},
    }
    parsed = parse_windows(record)
    assert parsed.event_type == "process_create"
    assert parsed.process == "powershell.exe"
    assert parsed.host == "WS-042"


async def test_windows_log_cleared_is_critical_mapped():
    record = {
        "source_type": "windows",
        "event_type": "log_cleared",
        "message": "log cleared",
        "raw": {"event_id": 1102, "computer": "DC-01"},
    }
    parsed = parse_windows(record)
    assert parsed.event_type == "log_cleared"


async def test_windows_unknown_event_id_maps_to_other():
    record = {
        "source_type": "windows",
        "event_type": "logon_success",
        "message": "weird",
        "raw": {"event_id": 9999},
    }
    parsed = parse_windows(record)
    assert parsed.event_type == "other"


async def test_windows_text_fallback_and_malformed():
    parsed = parse_windows({"source_type": "windows", "event_type": "logon_success", "message": "Logon failed for user bob (4625)"})
    assert parsed.event_type == "logon_failure"
    parsed = parse_windows({"source_type": "windows", "event_type": "logon_success", "message": "no event id here"})
    assert parsed.event_type is None
    parsed = parse_windows({"source_type": "windows", "event_type": "logon_success", "message": "(notanumber)"})
    assert parsed.event_type is None


# ---------------------------------------------------------------------------
# custom_json / test.
# ---------------------------------------------------------------------------


async def test_custom_json_lifts_fields_from_raw():
    record = {
        "source_type": "custom_json",
        "event_type": "custom",
        "message": "upstream alert",
        "raw": {"severity_hint": "high", "user": "svc-scan", "ip": "203.0.113.4", "hostname": "scanner-1"},
    }
    parsed = parse_custom_json(record)
    assert parsed.user == "svc-scan"
    assert parsed.ip == "203.0.113.4"
    assert parsed.host == "scanner-1"


async def test_test_data_parser_is_a_noop():
    parsed = parse_test({"source_type": "test", "event_type": "test_event", "message": "anything"})
    assert parsed.event_type is None


async def test_unknown_source_type_parser_falls_back():
    parsed = parse_record("does_not_exist", {"message": "x"})
    assert parsed.event_type is None
