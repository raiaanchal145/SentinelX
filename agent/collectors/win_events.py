"""
Windows Event Log Collector using native wevtapi.dll bindings.

Subscribes to Security, System, and Windows Defender channels using dynamic
consent-gated XPath queries and tracks bookmark state.
"""

from __future__ import annotations

import ctypes
import logging
import re
import sys
import xml.etree.ElementTree as ET
from ctypes import wintypes
from typing import Any, Callable, Generator, Optional

from agent.schema import (
    EVENT_ID_SEVERITY,
    EVENT_ID_TO_CATEGORY,
    EVENT_ID_TO_VOCABULARY,
    create_event_record,
)

logger = logging.getLogger("sentinelx.agent.collector")

# EvtRender flags
EvtRenderEventValues = 0
EvtRenderEventXml = 1
EvtRenderBookmark = 2

# EvtSubscribe flags
EvtSubscribeToFutureEvents = 1
EvtSubscribeStartAtOldestRecord = 2
EvtSubscribeStartAfterBookmark = 3

# EvtQuery flags
EvtQueryChannelPath = 0x1
EvtQueryReverseDirection = 0x200


def _load_wevtapi():
    if sys.platform != "win32":
        return None
    try:
        return ctypes.windll.wevtapi
    except Exception:
        return None


wevtapi = _load_wevtapi()


def build_channel_xpath(channel: str, enabled_categories: set[str] | list[str]) -> str | None:
    """
    Constructs an XPath query including ONLY Event IDs matching enabled consent categories.
    Returns None if no events in this channel are consented.
    """
    granted = set(enabled_categories)
    event_ids: list[int] = []

    if channel == "Security":
        if "authentication" in granted:
            event_ids.extend([4624, 4625, 4634, 4672, 4740])
        if "process_activity" in granted:
            event_ids.append(4688)
        if "system_integrity" in granted:
            event_ids.extend([4720, 4722, 4724, 4726, 1102])

    elif channel == "System":
        if "process_activity" in granted:
            event_ids.append(7045)

    elif channel == "Microsoft-Windows-Windows Defender/Operational":
        if "security_defenses" in granted:
            event_ids.extend([1116, 1117])

    if not event_ids:
        return None

    # Construct XPath filter: *[System[(EventID=4624 or EventID=4625)]]
    id_terms = " or ".join(f"EventID={eid}" for eid in sorted(event_ids))
    return f"*[System[({id_terms})]]"


def parse_event_xml(xml_content: str) -> dict[str, Any] | None:
    """
    Parses Windows Event XML representation into a normalized SentinelX event dictionary.
    Returns None if XML is invalid or unmapped.
    """
    try:
        # Strip default XML namespace for clean XPath querying
        clean_xml = re.sub(r' xmlns="[^"]+"', "", xml_content, count=1)
        root = ET.fromstring(clean_xml)
    except Exception as exc:
        logger.debug("Failed to parse event XML: %s", exc)
        return None

    system = root.find("System")
    if system is None:
        return None

    event_id_elem = system.find("EventID")
    if event_id_elem is None or not event_id_elem.text:
        return None

    try:
        event_id = int(event_id_elem.text.strip())
    except ValueError:
        return None

    event_type = EVENT_ID_TO_VOCABULARY.get(event_id)
    if not event_type:
        return None

    time_created = system.find("TimeCreated")
    timestamp = None
    if time_created is not None:
        timestamp = time_created.attrib.get("SystemTime")

    computer = system.findtext("Computer")
    record_id_elem = system.findtext("EventRecordID")
    record_id = int(record_id_elem) if record_id_elem and record_id_elem.isdigit() else None
    channel = system.findtext("Channel") or "Security"

    # Extract EventData key-value pairs
    data_dict: dict[str, Any] = {}
    event_data = root.find("EventData")
    if event_data is not None:
        for data in event_data.findall("Data"):
            name = data.attrib.get("Name")
            val = data.text or ""
            if name:
                data_dict[name] = val
            elif val:
                data_dict[f"Param{len(data_dict)+1}"] = val

    # User extraction
    target_user = data_dict.get("TargetUserName") or data_dict.get("SubjectUserName") or data_dict.get("UserName")
    domain = data_dict.get("TargetDomainName") or data_dict.get("SubjectDomainName")
    full_user = f"{domain}\\{target_user}" if (domain and target_user and domain not in ("-", "NT AUTHORITY", "WORKGROUP")) else target_user

    # IP / Host extraction
    ip = data_dict.get("IpAddress") or data_dict.get("WorkstationName")
    if ip in ("-", "::1", "127.0.0.1"):
        ip = None

    # Process extraction
    process = (
        data_dict.get("NewProcessName")
        or data_dict.get("ProcessName")
        or data_dict.get("ServiceName")
        or data_dict.get("ImagePath")
    )
    cmdline = data_dict.get("CommandLine")

    # Construct descriptive human-readable message
    if event_id == 4624:
        logon_type = data_dict.get("LogonType", "interactive")
        msg = f"Successful logon for '{full_user or 'User'}' (Type: {logon_type})"
        if ip:
            msg += f" from {ip}"
    elif event_id == 4625:
        sub_status = data_dict.get("SubStatus", data_dict.get("Status", "0xC000006A"))
        msg = f"Failed logon attempt for '{full_user or 'Unknown'}' ({sub_status})"
        if ip:
            msg += f" from {ip}"
    elif event_id == 4634:
        msg = f"User logoff: '{full_user or 'User'}'"
    elif event_id == 4672:
        msg = f"Special privileges assigned to logon session: '{full_user or 'Admin'}'"
    elif event_id == 4688:
        proc_name = process.split("\\")[-1] if process else "process"
        msg = f"Process created: {proc_name}"
        if cmdline:
            msg += f" [{cmdline[:120]}]"
    elif event_id == 4720:
        msg = f"User account created: '{data_dict.get('TargetUserName', 'User')}' by '{full_user or 'System'}'"
    elif event_id == 4722:
        msg = f"User account enabled: '{data_dict.get('TargetUserName', 'User')}'"
    elif event_id == 4724:
        msg = f"Password reset attempted for account: '{data_dict.get('TargetUserName', 'User')}'"
    elif event_id == 4726:
        msg = f"User account deleted: '{data_dict.get('TargetUserName', 'User')}' by '{full_user or 'System'}'"
    elif event_id == 4740:
        msg = f"User account locked out: '{data_dict.get('TargetUserName', 'User')}'"
    elif event_id == 7045:
        msg = f"New Windows service installed: '{data_dict.get('ServiceName', 'Service')}'"
        if data_dict.get("ImagePath"):
            msg += f" ({data_dict.get('ImagePath')})"
    elif event_id == 1102:
        msg = f"Security audit log cleared by user '{full_user or 'Administrator'}'"
    elif event_id in (1116, 1117):
        threat = data_dict.get("Threat Name") or data_dict.get("ThreatName") or "Malware"
        path = data_dict.get("Path") or data_dict.get("ThreatPath") or ""
        action = "Action taken" if event_id == 1117 else "Detected"
        msg = f"Windows Defender {action}: '{threat}' in {path}"
    else:
        msg = f"Windows event {event_id} ({event_type})"

    raw_payload: dict[str, Any] = {
        "event_id": event_id,
        "log_name": channel,
        "record_id": record_id,
        "computer": computer,
        "data": data_dict,
    }
    if cmdline:
        raw_payload["command_line"] = cmdline

    return create_event_record(
        event_type=event_type,
        message=msg,
        timestamp=timestamp,
        host=computer,
        user=full_user,
        ip=ip,
        process=process,
        severity_hint=EVENT_ID_SEVERITY.get(event_id, "info"),
        raw=raw_payload,
    )


class WindowsEventCollector:
    """Reads events from Windows Event Log channels."""

    def __init__(
        self,
        channels: Optional[list[str]] = None,
        get_bookmark_fn: Optional[Callable[[str], Optional[str]]] = None,
        set_bookmark_fn: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self.channels = channels or ["Security", "System", "Microsoft-Windows-Windows Defender/Operational"]
        self.get_bookmark = get_bookmark_fn or (lambda ch: None)
        self.set_bookmark = set_bookmark_fn or (lambda ch, bm: None)

    def is_available(self) -> bool:
        return wevtapi is not None

    def poll_events(
        self,
        enabled_categories: set[str] | list[str],
        max_events_per_channel: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Polls configured channels for new events matching enabled categories.
        Returns normalized SentinelX event records.
        """
        if not self.is_available():
            return []

        all_records: list[dict[str, Any]] = []

        for channel in self.channels:
            xpath = build_channel_xpath(channel, enabled_categories)
            if not xpath:
                # Category not consented for this channel: skip completely
                continue

            try:
                records = self._query_channel(channel, xpath, max_events_per_channel)
                all_records.extend(records)
            except Exception as exc:
                logger.debug("Channel %s query error: %s", channel, exc)

        return all_records

    def _query_channel(self, channel: str, xpath: str, limit: int) -> list[dict[str, Any]]:
        """Executes EvtQuery on a channel with bookmarks if supported."""
        records: list[dict[str, Any]] = []

        flags = EvtQueryChannelPath | EvtQueryReverseDirection
        query_handle = wevtapi.EvtQuery(None, channel, xpath, flags)
        if not query_handle:
            return []

        try:
            events_array = (wintypes.HANDLE * limit)()
            returned = wintypes.DWORD(0)

            success = wevtapi.EvtNext(query_handle, limit, events_array, 2000, 0, ctypes.byref(returned))
            count = returned.value

            if not count:
                return []

            # Process events in chronological order (reverse of query)
            for i in reversed(range(count)):
                evt_h = events_array[i]
                if not evt_h:
                    continue
                try:
                    xml_str = self._render_event_xml(evt_h)
                    if xml_str:
                        rec = parse_event_xml(xml_str)
                        if rec:
                            records.append(rec)
                finally:
                    wevtapi.EvtClose(evt_h)

        finally:
            wevtapi.EvtClose(query_handle)

        return records

    def _render_event_xml(self, event_handle) -> str | None:
        """Renders event handle to XML string."""
        buffer_size = wintypes.DWORD(0)
        buffer_used = wintypes.DWORD(0)
        prop_count = wintypes.DWORD(0)

        # First call gets required buffer size
        wevtapi.EvtRender(None, event_handle, EvtRenderEventXml, 0, None, ctypes.byref(buffer_used), ctypes.byref(prop_count))
        req_size = buffer_used.value
        if not req_size:
            return None

        buf = ctypes.create_unicode_buffer(req_size // 2 + 2)
        success = wevtapi.EvtRender(
            None,
            event_handle,
            EvtRenderEventXml,
            req_size,
            buf,
            ctypes.byref(buffer_used),
            ctypes.byref(prop_count),
        )
        if success:
            return buf.value
        return None
