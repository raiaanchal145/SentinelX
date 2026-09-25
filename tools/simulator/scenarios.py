"""
Scenario generators for the SentinelX demo simulator (tools/simulator).

Each scenario is a pure function of (seed, scenario_name) -> list of
event records matching the P07 ingestion schema
(docs/API_CONTRACT.md "Event ingestion", schema_version 1.0). The
senders pace the output; the generators know nothing about HTTP, rate
or duration -- rate and duration only decide WHICH slice of the
generated sequence gets sent (repeating the sequence when it is
shorter than the requested run).

Determinism: everything is drawn from one random.Random(seed), so the
same seed produces byte-identical event lists for a scenario. Timestamps
are the only relative part -- they are spread backward from a base
"now" so a 60-second demo shows a plausible timeline without waiting.

Labeling and safety:
  - every event carries {"sim": {"scenario": <name>}} inside `raw` so
    tests and demo cleanup can find exactly what the simulator sent;
  - users are synthetic role names, hosts are lab hostnames, IPs come
    exclusively from the RFC 5737 documentation ranges (192.0.2.0/24,
    198.51.100.0/24, 203.0.113.0/24) and RFC 1918 private space --
    never real personal data.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

SCHEMA_VERSION = "1.0"

# Documentation-only + private address space. The simulator never
# emits a routable public IP.
SIM_IP_POOLS = {
    "internal": ["10.0.0.11", "10.0.0.12", "10.0.0.13", "10.0.0.14"],
    "attackers": ["203.0.113.66", "203.0.113.67", "198.51.100.24", "192.0.2.88"],
}

LAB_HOSTS = ["lab-win01", "lab-win02", "lab-app01", "lab-db01", "lab-fw01"]
LAB_USERS = ["alice.analyst", "bob.dev", "svc.backup", "svc.build", "carol.manager"]

# A short, fixed word list -- no real person, company or project names.
APP_NAMES = ["sentinelx-api", "payments-svc", "billing-worker", "reporting-job"]


def _marker(scenario: str) -> dict:
    return {"sim": {"scenario": scenario}}


def _base(scenario: str, rng: random.Random, occurred_at: datetime, **fields) -> dict:
    record = {
        "schema_version": SCHEMA_VERSION,
        "timestamp": occurred_at.isoformat(),
        "source_type": fields.pop("source_type"),
        "event_type": fields.pop("event_type"),
        "message": fields.pop("message"),
        "host": fields.pop("host", None),
        "asset": fields.pop("asset", None),
        "user": fields.pop("user", None),
        "ip": fields.pop("ip", None),
        "process": fields.pop("process", None),
        "severity_hint": fields.pop("severity_hint", None),
        "raw": fields.pop("raw", None),
    }
    if record["raw"] is None:
        record["raw"] = {}
    if isinstance(record["raw"], dict):
        record["raw"]["sim"] = {"scenario": scenario}
    record["_scenario"] = scenario
    record["_leftover_fields"] = fields
    return record


def _pick(rng: random.Random, items):
    return rng.choice(items)


def _host(rng: random.Random) -> str:
    return _pick(rng, LAB_HOSTS)


def _user(rng: random.Random) -> str:
    return _pick(rng, LAB_USERS)


def _internal_ip(rng: random.Random) -> str:
    return _pick(rng, SIM_IP_POOLS["internal"])


def _attacker_ip(rng: random.Random) -> str:
    return _pick(rng, SIM_IP_POOLS["attackers"])


# ---------------------------------------------------------------------------
# The scenarios. Each returns a list of event dicts in chronological
# order (oldest first). The counts are part of each scenario's contract
# and pinned by tests.
# ---------------------------------------------------------------------------


def ssh_or_windows_bruteforce(rng: random.Random, now: datetime) -> list[dict]:
    """20 failed logons -> 1 success -> 1 privileged command (22 events)."""
    events: list[dict] = []
    host = "lab-win01"
    target = _user(rng)
    attacker = _attacker_ip(rng)
    t0 = now

    for i in range(20):
        events.append(
            _base(
                "ssh_or_windows_bruteforce",
                rng,
                t0 + timedelta(seconds=i * 2),
                source_type="windows",
                event_type="logon_failure",
                host=host,
                user=target,
                ip=attacker,
                process="winlogon.exe",
                severity_hint="medium" if i >= 15 else None,
                message=f"Logon failed for user {target} from {attacker} (4625) -- attempt {i + 1} of 20",
                raw={"event_id": 4625, "computer": host, "target_user": target, "source_ip": attacker, "attempt": i + 1},
            )
        )

    events.append(
        _base(
            "ssh_or_windows_bruteforce",
            rng,
            t0 + timedelta(seconds=45),
            source_type="windows",
            event_type="logon_success",
            host=host,
            user=target,
            ip=attacker,
            process="winlogon.exe",
            severity_hint="high",
            message=f"Logon succeeded for user {target} from {attacker} (4624) after 20 failures",
            raw={"event_id": 4624, "computer": host, "target_user": target, "source_ip": attacker},
        )
    )
    events.append(
        _base(
            "ssh_or_windows_bruteforce",
            rng,
            t0 + timedelta(seconds=55),
            source_type="windows",
            event_type="process_create",
            host=host,
            user=target,
            ip=attacker,
            process="cmd.exe",
            severity_hint="high",
            message="Process created: net group \"Domain Admins\" (4688) -- privileged command after brute force",
            raw={"event_id": 4688, "computer": host, "process_name": "cmd.exe", "command_line": "net group \"Domain Admins\""},
        )
    )
    return events


def privilege_escalation(rng: random.Random, now: datetime) -> list[dict]:
    """sudo/group changes/permission changes building toward admin (6 events)."""
    events: list[dict] = []
    host = "lab-app01"
    actor = _user(rng)
    t0 = now

    events.append(
        _base(
            "privilege_escalation",
            rng, t0,
            source_type="linux_auth", event_type="sudo_command",
            host=host, user=actor, ip=_internal_ip(rng), process="sudo",
            severity_hint="low",
            message=f"{actor} : TTY=pts/0 ; PWD=/home/{actor} ; USER=root ; COMMAND=/usr/bin/id",
            raw={"command": "/usr/bin/id"},
        )
    )
    events.append(
        _base(
            "privilege_escalation",
            rng, t0 + timedelta(seconds=30),
            source_type="linux_auth", event_type="group_change",
            host=host, user=actor, ip=_internal_ip(rng), process="usermod",
            message=f"add '{actor}' to group 'sudo'",
            raw={"group": "sudo"},
        )
    )
    events.append(
        _base(
            "privilege_escalation",
            rng, t0 + timedelta(seconds=70),
            source_type="application", event_type="permission_change",
            host=host, user=actor, ip=_internal_ip(rng), process="sentinelx-api",
            severity_hint="medium",
            message="Permissions on /etc/sentinelx/config.yaml changed: owner root -> owner " + actor,
            raw={"resource": "/etc/sentinelx/config.yaml", "change": "owner"},
        )
    )
    events.append(
        _base(
            "privilege_escalation",
            rng, t0 + timedelta(seconds=110),
            source_type="linux_auth", event_type="sudo_command",
            host=host, user=actor, ip=_internal_ip(rng), process="sudo",
            severity_hint="high",
            message=f"{actor} : TTY=pts/0 ; PWD=/root ; USER=root ; COMMAND=/usr/bin/passwd root",
            raw={"command": "/usr/bin/passwd root"},
        )
    )
    events.append(
        _base(
            "privilege_escalation",
            rng, t0 + timedelta(seconds=150),
            source_type="linux_auth", event_type="group_change",
            host=host, user=actor, ip=_internal_ip(rng), process="usermod",
            severity_hint="high",
            message=f"add '{actor}' to group 'wheel'",
            raw={"group": "wheel"},
        )
    )
    events.append(
        _base(
            "privilege_escalation",
            rng, t0 + timedelta(seconds=190),
            source_type="windows", event_type="account_disabled",
            host="lab-win02", user="carol.manager", ip=_internal_ip(rng),
            severity_hint="medium",
            message="A user account was disabled (4722) during privilege escalation cleanup",
            raw={"event_id": 4722, "computer": "lab-win02"},
        )
    )
    return events


def new_user_created(rng: random.Random, now: datetime) -> list[dict]:
    """Account created on Linux and Windows + a first login (3 events)."""
    events: list[dict] = []
    host = _host(rng)
    new_user = f"svc.{_pick(rng, ['deploy', 'monitor', 'audit'])}"
    ip = _internal_ip(rng)

    events.append(
        _base(
            "new_user_created", rng, now,
            source_type="linux_auth", event_type="user_add",
            host=host, user=new_user, ip=ip, process="useradd",
            message=f"new user: name={new_user}, UID=1010, GID=1010, home=/home/{new_user}, shell=/bin/bash",
            raw={"new_user": new_user},
        )
    )
    events.append(
        _base(
            "new_user_created", rng, now + timedelta(seconds=25),
            source_type="windows", event_type="account_created",
            host=host, user=new_user, ip=ip,
            message=f"A user account was created (4720): {new_user}",
            raw={"event_id": 4720, "computer": host, "target_user": new_user},
        )
    )
    events.append(
        _base(
            "new_user_created", rng, now + timedelta(seconds=60),
            source_type="application", event_type="app_login",
            host=host, user=new_user, ip=ip, process="sentinelx-api",
            message=f"Application login succeeded for {new_user} (first login for this account)",
            raw={"first_login": True},
        )
    )
    return events


def service_installed(rng: random.Random, now: datetime) -> list[dict]:
    """A new Windows service -- classic persistence (2 events)."""
    service_name = f"SimSvc{_pick(rng, ['Update', 'Monitor', 'Helper'])}"
    host = "lab-win02"

    return [
        _base(
            "service_installed", rng, now,
            source_type="windows", event_type="service_install",
            host=host, user="SYSTEM", ip=_internal_ip(rng),
            severity_hint="high",
            message=f"Service installed (7045): {service_name} -- %SystemRoot%\\simsvc.exe, start type auto",
            raw={"event_id": 7045, "computer": host, "service_name": service_name, "image_path": "%SystemRoot%\\simsvc.exe"},
        ),
        _base(
            "service_installed", rng, now + timedelta(seconds=20),
            source_type="windows", event_type="process_create",
            host=host, user="SYSTEM", ip=_internal_ip(rng),
            message=f"Process created: {service_name}.exe (4688)",
            raw={"event_id": 4688, "computer": host, "process_name": "simsvc.exe"},
        ),
    ]


def audit_log_cleared(rng: random.Random, now: datetime) -> list[dict]:
    """The security log was cleared -- always suspicious (2 events)."""
    host = "lab-win01"
    actor = _user(rng)

    return [
        _base(
            "audit_log_cleared", rng, now,
            source_type="windows", event_type="log_cleared",
            host=host, user=actor, ip=_internal_ip(rng),
            severity_hint="critical",
            message="The Windows event log was cleared (1102) by " + actor,
            raw={"event_id": 1102, "computer": host},
        ),
        _base(
            "audit_log_cleared", rng, now + timedelta(seconds=15),
            source_type="windows", event_type="logon_success",
            host=host, user=actor, ip=_internal_ip(rng),
            message=f"Logon succeeded for user {actor} (4624) immediately before the log clear",
            raw={"event_id": 4624, "computer": host, "target_user": actor},
        ),
    ]


def suspicious_download(rng: random.Random, now: datetime) -> list[dict]:
    """File created with a Zone.Identifier (Mark of the Web) + a hash (3 events)."""
    host = "lab-win02"
    user = _user(rng)
    url = f"http://203.0.113.{_pick(rng, [66, 67])}/dl/loader_v{_pick(rng, [2, 3, 7])}.exe"
    file_name = f"loader_v{_pick(rng, [2, 3, 7])}.exe"
    file_hash = "".join(rng.choice("0123456789abcdef") for _ in range(64))

    return [
        _base(
            "suspicious_download", rng, now,
            source_type="windows", event_type="process_create",
            host=host, user=user, ip=_internal_ip(rng), process="msedge.exe",
            severity_hint="medium",
            message=f"Process created: msedge.exe downloading {url} (4688)",
            raw={"event_id": 4688, "computer": host, "process_name": "msedge.exe", "download_url": url},
        ),
        _base(
            "suspicious_download", rng, now + timedelta(seconds=12),
            source_type="windows", event_type="process_create",
            host=host, user=user, ip=_internal_ip(rng), process="explorer.exe",
            severity_hint="high",
            message=f"File created: C:\\Users\\{user}\\Downloads\\{file_name}:Zone.Identifier -- Mark of the Web present",
            raw={
                "event_id": 4688,
                "computer": host,
                "file_name": file_name,
                "zone_identifier": 3,  # Internet zone
                "sha256": file_hash,
            },
        ),
        _base(
            "suspicious_download", rng, now + timedelta(seconds=40),
            source_type="application", event_type="app_warning",
            host=host, user=user, ip=_internal_ip(rng), process="sentinelx-api",
            message=f"Executable downloaded from the internet: {file_name} sha256={file_hash[:16]}... (quarantined)",
            raw={"file_name": file_name, "sha256": file_hash},
        ),
    ]


def benign_noise(rng: random.Random, now: datetime) -> list[dict]:
    """Normal activity, for false-positive testing (12 events)."""
    events: list[dict] = []

    for i in range(4):
        events.append(
            _base(
                "benign_noise", rng, now + timedelta(seconds=i * 90),
                source_type="linux_auth", event_type="auth_success",
                host=lab_host if (lab_host := _host(rng)) else None,
                user=_user(rng), ip=_internal_ip(rng), process="sshd",
                message=f"Accepted publickey for {_user(rng)} from {_internal_ip(rng)} port {_pick(rng, [41000, 51200, 55100])} ssh2",
                raw={"auth": "publickey"},
            )
        )

    for i in range(3):
        app = _pick(rng, APP_NAMES)
        level = _pick(rng, ["info", "info", "warning"])
        events.append(
            _base(
                "benign_noise", rng, now + timedelta(seconds=30 + i * 100),
                source_type="application", event_type="app_error" if level == "warning" else "app_login",
                host=_host(rng), user=_user(rng), ip=_internal_ip(rng), process=app,
                severity_hint=None,
                message=f"{app}: routine {level} entry -- scheduled job completed without action needed",
                raw={"level": level, "logger": app},
            )
        )

    for i in range(3):
        events.append(
            _base(
                "benign_noise", rng, now + timedelta(seconds=45 + i * 110),
                source_type="docker", event_type=_pick(rng, ["container_start", "container_stop"]),
                host=_host(rng), process=_pick(rng, APP_NAMES),
                message=f"container {_pick(rng, ['web', 'worker', 'cache'])} started/stopped by the scheduler",
                raw={"status": "start" if i % 2 == 0 else "stop", "Actor": {"Attributes": {"name": "cache"}}},
            )
        )

    events.append(
        _base(
            "benign_noise", rng, now + timedelta(seconds=60),
            source_type="network", event_type="firewall_allow",
            host="lab-fw01", ip=_internal_ip(rng), process="iptables",
            message=f"iptables ACCEPT IN=eth0 SRC={_internal_ip(rng)} DST={_internal_ip(rng)} PROTO=TCP DPT=443",
            raw={"action": "accept", "src_ip": _internal_ip(rng), "dst_port": 443},
        )
    )
    events.append(
        _base(
            "benign_noise", rng, now + timedelta(seconds=75),
            source_type="network", event_type="dns_query",
            host="lab-fw01", ip=_internal_ip(rng), process="dnsmasq",
            message="DNS query observed for updates.example.internal (A) -- resolved from the internal resolver",
            raw={"domain": "updates.example.internal", "qtype": "A"},
        )
    )
    return events


def mixed(rng: random.Random, now: datetime) -> list[dict]:
    """Noise plus one attack: bruteforce appended to benign noise (34 events)."""
    return benign_noise(rng, now) + ssh_or_windows_bruteforce(rng, now + timedelta(seconds=200))


# ---------------------------------------------------------------------------
# Registry -- the single source of truth for --list and __main__.
# ---------------------------------------------------------------------------

SCENARIOS: dict[str, callable] = {
    "ssh_or_windows_bruteforce": ssh_or_windows_bruteforce,
    "privilege_escalation": privilege_escalation,
    "new_user_created": new_user_created,
    "service_installed": service_installed,
    "audit_log_cleared": audit_log_cleared,
    "suspicious_download": suspicious_download,
    "benign_noise": benign_noise,
    "mixed": mixed,
}

SCENARIO_DESCRIPTIONS: dict[str, str] = {
    "ssh_or_windows_bruteforce": "20 failed logons, then a success, then a privileged command (22 events)",
    "privilege_escalation": "sudo -> group change -> permission change -> passwd root (6 events)",
    "new_user_created": "account created on Linux + Windows, then a first application login (3 events)",
    "service_installed": "a new Windows service registered and its process created (2 events)",
    "audit_log_cleared": "the Windows security log was cleared -- critical severity (2 events)",
    "suspicious_download": "executable downloaded with a Zone.Identifier marker and a sha256 (3 events)",
    "benign_noise": "normal logins and activity, for false-positive testing (12 events)",
    "mixed": "benign noise plus one brute-force attack (34 events)",
}


def generate(scenario: str, seed: int, base_time: datetime | None = None) -> list[dict]:
    """The one entry point senders and tests use: (scenario, seed) ->
    the full event list, oldest first, every event tagged with its
    scenario marker inside raw."""
    if scenario not in SCENARIOS:
        raise KeyError(f"unknown scenario '{scenario}' -- known: {', '.join(sorted(SCENARIOS))}")
    rng = random.Random(seed)
    now = base_time or datetime.now(timezone.utc)
    return SCENARIOS[scenario](rng, now)
