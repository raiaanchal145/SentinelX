"""
Per-source-type parsers: raw records -> the normalized schema (P07).

Each parser takes the validated ingestion record (docs/API_CONTRACT.md
"Event ingestion" -- the payload the collector sent) and returns a
`Parsed` with whatever it could extract from the raw content. The raw
content is the record's `raw` field if the collector supplied one, else
the message text itself -- syslog-style sources ship the original line
as the message; JSON sources ship an object.

Merge rules (see docs/DECISIONS.md "Parser output vs the declared
event_type"):
  - extracted FIELDS fill blanks -- a value the collector explicitly
    sent always wins over a parser guess;
  - if the parser RECOGNIZES the raw content and derives a concrete
    classification, its event_type wins (raw content is ground truth --
    a collector that mislabels "Failed password" as auth_success does
    not get to keep the mislabel);
  - if the parser derives a concrete verb that has NO mapping in the
    fixed vocabulary, the event is stored with event_type "other" and
    the raw record kept verbatim;
  - if the parser recognizes nothing at all (unparseable text), the
    collector's declared event_type is kept -- it is already guaranteed
    to be in the vocabulary by the API -- and the raw record is kept.

Parsers are pure functions -- no DB, no I/O -- so tests can pin them on
real sample lines.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Parsed:
    """What a parser extracted. event_type None means "keep the declared
    type"; "other" means "unmappable -- keep raw, classify as other"."""

    event_type: str | None = None
    host: str | None = None
    user: str | None = None
    ip: str | None = None
    process: str | None = None
    extracted: dict[str, Any] = field(default_factory=dict)


# Syslog prefix: "Jan 12 03:14:15 web01 sshd[2201]: <message>"
_SYSLOG_PREFIX = re.compile(
    r"^(?P<month>[A-Z][a-z]{2})\s+(?P<day>\d{1,2})\s+(?P<time>\d{2}:\d{2}:\d{2})\s+"
    r"(?P<host>\S+)\s+(?P<proc>[\w.~/-]+)(?:\[(?P<pid>\d+)\])?:\s*(?P<rest>.*)$"
)


def _effective_text(record: dict) -> str:
    raw = record.get("raw")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    if isinstance(raw, dict):
        return json.dumps(raw, default=str)
    return str(record.get("message") or "")


def _split_syslog(text: str) -> tuple[str | None, str | None, str]:
    """(host, process, message-body) from an optional syslog prefix."""
    m = _SYSLOG_PREFIX.match(text)
    if m:
        return m.group("host"), m.group("proc"), m.group("rest")
    return None, None, text


# ---------------------------------------------------------------------------
# linux_auth
# ---------------------------------------------------------------------------

_LINUX_PATTERNS: list[tuple[re.Pattern, str | None]] = [
    (re.compile(r"Failed password for (?:invalid user )?(?P<user>\S+) from (?P<ip>\S+) port (?P<port>\d+)", re.I), "auth_failure"),
    (re.compile(r"Invalid user (?P<user>\S+) from (?P<ip>\S+) port (?P<port>\d+)", re.I), "auth_failure"),
    (re.compile(r"Accepted (?:password|publickey|keyboard-interactive/pam) for (?P<user>\S+) from (?P<ip>\S+) port (?P<port>\d+)", re.I), "auth_success"),
    (re.compile(r"Connection closed by authenticating user (?P<user>\S+) (?P<ip>\S+) port (?P<port>\d+)", re.I), "auth_failure"),
    # sudo: the syslog prefix has already split "sudo" off as the process,
    # so match both the bare "alice : TTY=..." body and a full
    # "sudo:   alice : TTY=..." line (no-prefix input).
    (re.compile(r"(?:^sudo:\s+)?(?P<user>[\w.\-]+)\s+:\s+(?P<rest>(?:TTY|PWD|USER|COMMAND)=.*)$"), "sudo_command"),
    # su[123]: (to root) alice on pts/0 -- recognized, no vocabulary mapping.
    (re.compile(r"\(to (?P<user>[\w.\-]+)\)"), None),
    (re.compile(r"new user: name=(?P<user>[\w.\-]+)", re.I), "user_add"),
    (re.compile(r"delete user '(?P<user>[\w.\-]+)'", re.I), "user_delete"),
    (re.compile(r"new group: name=(?P<group>[\w.\-]+)", re.I), "group_change"),
    (re.compile(r"add '(?P<user>[\w.\-]+)' to group '(?P<group>[\w.\-]+)'", re.I), "group_change"),
    (re.compile(r"pam_unix\((?P<service>[\w-]+):session\): session (?P<what>opened|closed) for user (?P<user>\S+)", re.I), None),
]


def parse_linux_auth(record: dict) -> Parsed:
    text = _effective_text(record)
    host, process, body = _split_syslog(text)
    parsed = Parsed(host=host, process=process)

    for pattern, event_type in _LINUX_PATTERNS:
        m = pattern.search(body)
        if not m:
            continue
        groups = m.groupdict()
        parsed.user = groups.get("user") or parsed.user
        parsed.ip = groups.get("ip") or parsed.ip
        detail = {k: v for k, v in groups.items() if k not in ("user", "ip") and v}
        # sudo lines: split the "TTY=.. ; PWD=.. ; USER=.. ; COMMAND=.."
        # tail into a real dict instead of one long string.
        if "rest" in detail and "=" in detail["rest"]:
            pairs = re.findall(r"(TTY|PWD|USER|COMMAND)=([^;]+)", detail.pop("rest"))
            detail["sudo"] = {k: v.strip() for k, v in pairs}
        parsed.extracted = {"matched": pattern.pattern[:60], **detail}
        if event_type is None:
            # Recognized line, but no vocabulary mapping of its own (su,
            # pam session open/close...) -- keep the declared type.
            return parsed
        parsed.event_type = event_type
        return parsed

    # Recognized as syslog but not one of the known auth lines.
    if host is not None or process is not None:
        return parsed
    return parsed  # unparseable: caller keeps the declared type


# ---------------------------------------------------------------------------
# application
# ---------------------------------------------------------------------------

_APP_LEVELS = {
    "error": "app_error",
    "fatal": "app_error",
    "critical": "app_error",
    "warning": "app_warning",
    "warn": "app_warning",
    "info": None,
    "debug": None,
}


def parse_application(record: dict) -> Parsed:
    raw = record.get("raw")

    if isinstance(raw, dict):
        parsed = Parsed()
        level = str(raw.get("level") or record.get("severity_hint") or "").lower()
        mapped = _APP_LEVELS.get(level)
        if mapped:
            parsed.event_type = mapped
        message = raw.get("message") or raw.get("msg")
        if message:
            parsed.extracted["message"] = str(message)
        for src_key, dst in (("user", "user"), ("ip", "ip"), ("host", "host"), ("service", "process"), ("logger", "process")):
            value = raw.get(src_key)
            if value:
                setattr(parsed, dst, str(value))
        return parsed

    # logfmt: level=error msg="Payment timeout" user=alice ip=10.1.2.3
    logfmt = re.compile(r'(\w+)=("[^"]*"|\S+)')
    pairs = {k: v.strip('"') for k, v in logfmt.findall(_effective_text(record))}
    if pairs:
        parsed = Parsed()
        mapped = _APP_LEVELS.get(pairs.get("level", "").lower())
        if mapped:
            parsed.event_type = mapped
        parsed.user = pairs.get("user")
        parsed.ip = pairs.get("ip") or pairs.get("client_ip")
        parsed.host = pairs.get("host")
        parsed.process = pairs.get("service") or pairs.get("logger")
        parsed.extracted = {"logfmt": {k: v for k, v in pairs.items() if k not in ("msg",)}}
        return parsed

    # Bracketed: "2026-09-24 10:11:12 ERROR [billing] Payment timeout"
    # (date, then optional time token, then the level).
    bracketed = re.match(r"^\S+(?:\s+\S+)?\s+(?P<level>ERROR|WARN(?:ING)?|INFO|DEBUG|CRITICAL|FATAL)\s+\[(?P<proc>[\w.-]+)\]\s+(?P<rest>.*)$", record.get("message") or "", re.I)
    if bracketed:
        parsed = Parsed(process=bracketed.group("proc"))
        mapped = _APP_LEVELS.get(bracketed.group("level").lower())
        if mapped:
            parsed.event_type = mapped
        parsed.extracted = {"detail": bracketed.group("rest")}
        return parsed

    return Parsed()  # unparseable: keep declared type


# ---------------------------------------------------------------------------
# docker
# ---------------------------------------------------------------------------

_DOCKER_STATUS_MAP = {
    "start": "container_start",
    "stop": "container_stop",
    "die": "container_kill",
    "kill": "container_kill",
    "oom": "container_kill",
    "create": "container_create",
    "destroy": "container_destroy",
    "pull": "image_pull",
    "push": "image_push",
}


def parse_docker(record: dict) -> Parsed:
    raw = record.get("raw")

    if isinstance(raw, dict):
        status = str(raw.get("status") or raw.get("Action") or "").lower()
        event_type = _DOCKER_STATUS_MAP.get(status, "other") if status else None
        actor = raw.get("Actor") or {}
        attrs = actor.get("Attributes") or raw.get("Attributes") or {}
        return Parsed(
            event_type=event_type,
            host=attrs.get("host") or attrs.get("node") or record.get("host"),
            process=attrs.get("name") or attrs.get("container") or raw.get("id"),
            extracted={"image": attrs.get("image"), "status": status or None, "container_id": actor.get("ID") or raw.get("id")},
        )

    # Plain daemon line: "container abc123: start nginx:latest"
    text = _effective_text(record)
    m = re.match(r"^(?P<kind>container|image)\s+(?P<id>\S+)(?:\s+from\s+(?P<image>\S+))?\s*:\s*(?P<status>\S+)", text, re.I)
    if m:
        status = m.group("status").lower()
        return Parsed(
            event_type=_DOCKER_STATUS_MAP.get(status, "other"),
            process=m.group("id"),
            extracted={"image": m.group("image"), "status": status},
        )
    return Parsed()


# ---------------------------------------------------------------------------
# network
# ---------------------------------------------------------------------------

_NET_ACTION_MAP = {
    "deny": "firewall_deny",
    "drop": "firewall_deny",
    "reject": "firewall_deny",
    "block": "firewall_deny",
    "blocked": "connection_blocked",
    "blockedconnection": "connection_blocked",
    "accept": "firewall_allow",
    "allow": "firewall_allow",
    "permitted": "connection_allowed",
}


def parse_network(record: dict) -> Parsed:
    raw = record.get("raw")

    if isinstance(raw, dict):
        action = str(raw.get("action") or raw.get("verdict") or "").lower()
        event_type = _NET_ACTION_MAP.get(action) if action else None
        if raw.get("scan_detected") or raw.get("port_scan"):
            event_type = "port_scan"
        if raw.get("signature"):
            event_type = event_type or "ids_alert"
        return Parsed(
            event_type=event_type,
            host=str(raw.get("host") or record.get("host") or "") or None,
            user=str(raw.get("user") or "") or None,
            ip=str(raw.get("src_ip") or raw.get("source_ip") or "") or None,
            process=str(raw.get("device") or raw.get("interface") or "") or None,
            extracted={k: raw[k] for k in ("dst_ip", "dst_port", "src_port", "proto", "protocol", "signature", "device") if raw.get(k) is not None},
        )

    # iptables/netfilter kernel line:
    # "iptables DENY IN=eth0 SRC=203.0.113.9 DST=10.0.0.5 PROTO=TCP DPT=22"
    text = _effective_text(record)
    m = re.match(r"^(?P<proc>[\w-]+)\s+(?P<action>DENY|DROP|REJECT|ACCEPT|ALLOW|BLOCK)\b", text, re.I)
    fields = dict(re.findall(r"\b(SRC|DST|PROTO|DPT|SPT|IN|OUT)=(\S+)", text))
    if m or fields:
        action = m.group("action").lower() if m else None
        event_type = _NET_ACTION_MAP.get(action) if action else None
        if "scan" in text.lower():
            event_type = "port_scan"
        return Parsed(
            event_type=event_type,
            process=m.group("proc") if m else fields.get("IN"),
            ip=fields.get("SRC"),
            extracted={"dst_ip": fields.get("DST"), "dst_port": fields.get("DPT"), "src_port": fields.get("SPT"), "proto": fields.get("PROTO"), "interface": fields.get("IN")},
        )
    return Parsed()


# ---------------------------------------------------------------------------
# windows (the P21 endpoint agent)
# ---------------------------------------------------------------------------

_WINDOWS_EVENT_ID_MAP = {
    4624: "logon_success",
    4625: "logon_failure",
    4688: "process_create",
    7045: "service_install",
    4720: "account_created",
    4722: "account_disabled",
    4740: "account_lockout",
    1102: "log_cleared",
    4719: "policy_change",
    4698: "scheduled_task",
    4699: "scheduled_task",
}


def parse_windows(record: dict) -> Parsed:
    raw = record.get("raw")

    if isinstance(raw, dict):
        event_id = raw.get("event_id") or raw.get("EventID") or raw.get("eventId")
        try:
            event_id = int(event_id)
        except (TypeError, ValueError):
            event_id = None
        event_type = _WINDOWS_EVENT_ID_MAP.get(event_id, "other") if event_id else None
        return Parsed(
            event_type=event_type,
            host=str(raw.get("host") or raw.get("computer") or record.get("host") or "") or None,
            user=str(raw.get("user") or raw.get("target_user") or "") or None,
            ip=str(raw.get("ip") or raw.get("source_ip") or "") or None,
            process=str(raw.get("process") or raw.get("process_name") or "") or None,
            extracted={"event_id": event_id, "log_name": raw.get("log_name") or raw.get("channel")},
        )

    # Text fallback: "Logon failed for user alice from 10.0.0.8 (4625)"
    text = _effective_text(record)
    m = re.search(r"\((?P<id>\d{4})\)", text)
    if m:
        event_id = int(m.group("id"))
        return Parsed(event_type=_WINDOWS_EVENT_ID_MAP.get(event_id, "other"), extracted={"event_id": event_id})
    return Parsed()


# ---------------------------------------------------------------------------
# custom_json / test: the collector pre-structured the record; nothing to
# re-derive. Keep the declared event_type (guaranteed in the vocabulary by
# the API); lift user/ip/host out of raw if the payload fields are blank.
# ---------------------------------------------------------------------------


def parse_custom_json(record: dict) -> Parsed:
    raw = record.get("raw")
    parsed = Parsed()
    if isinstance(raw, dict):
        for src_keys, dst in ((("user", "username"), "user"), (("ip", "src_ip", "source_ip"), "ip"), (("host", "hostname"), "host")):
            for key in src_keys:
                value = raw.get(key)
                if value and not getattr(parsed, dst):
                    setattr(parsed, dst, str(value))
        parsed.extracted = {k: raw[k] for k in raw if k not in ("raw",) and isinstance(raw[k], (str, int, float, bool))}
    return parsed


def parse_test(record: dict) -> Parsed:
    return Parsed()


PARSERS = {
    "linux_auth": parse_linux_auth,
    "application": parse_application,
    "docker": parse_docker,
    "network": parse_network,
    "windows": parse_windows,
    "custom_json": parse_custom_json,
    "test": parse_test,
}


def parse_record(source_type: str, record: dict) -> Parsed:
    parser = PARSERS.get(source_type)
    if parser is None:
        return Parsed()
    try:
        return parser(record)
    except Exception:  # noqa: BLE001 -- a parser bug must never drop an event
        return Parsed(extracted={"parser_error": True})
