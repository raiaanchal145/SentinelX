"""
Unit Tests for Windows Event Log XML Parsing and SentinelX Vocabulary Mapping.
"""

import pytest
from agent.collectors.win_events import parse_event_xml

SAMPLE_4624_LOGON_SUCCESS = """
<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">
  <System>
    <Provider Name="Microsoft-Windows-Security-Auditing" />
    <EventID>4624</EventID>
    <TimeCreated SystemTime="2026-10-21T08:15:30.123456Z" />
    <EventRecordID>1001</EventRecordID>
    <Channel>Security</Channel>
    <Computer>LAB-WORKSTATION-01</Computer>
  </System>
  <EventData>
    <Data Name="TargetUserName">alice</Data>
    <Data Name="TargetDomainName">CORP</Data>
    <Data Name="LogonType">2</Data>
    <Data Name="IpAddress">192.168.1.100</Data>
  </EventData>
</Event>
"""

SAMPLE_4625_LOGON_FAILURE = """
<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">
  <System>
    <Provider Name="Microsoft-Windows-Security-Auditing" />
    <EventID>4625</EventID>
    <TimeCreated SystemTime="2026-10-21T08:16:00.654321Z" />
    <EventRecordID>1002</EventRecordID>
    <Channel>Security</Channel>
    <Computer>LAB-WORKSTATION-01</Computer>
  </System>
  <EventData>
    <Data Name="TargetUserName">bob</Data>
    <Data Name="TargetDomainName">CORP</Data>
    <Data Name="Status">0xC000006D</Data>
    <Data Name="SubStatus">0xC000006A</Data>
    <Data Name="IpAddress">10.0.0.50</Data>
  </EventData>
</Event>
"""

SAMPLE_4688_PROCESS_CREATE = """
<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">
  <System>
    <Provider Name="Microsoft-Windows-Security-Auditing" />
    <EventID>4688</EventID>
    <TimeCreated SystemTime="2026-10-21T08:17:00.000000Z" />
    <EventRecordID>1003</EventRecordID>
    <Channel>Security</Channel>
    <Computer>LAB-WORKSTATION-01</Computer>
  </System>
  <EventData>
    <Data Name="SubjectUserName">admin</Data>
    <Data Name="NewProcessName">C:\\Windows\\System32\\cmd.exe</Data>
    <Data Name="CommandLine">cmd.exe /c whoami</Data>
    <Data Name="ParentProcessName">C:\\Windows\\explorer.exe</Data>
  </EventData>
</Event>
"""

SAMPLE_7045_SERVICE_INSTALL = """
<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">
  <System>
    <Provider Name="Service Control Manager" />
    <EventID>7045</EventID>
    <TimeCreated SystemTime="2026-10-21T08:18:00.000000Z" />
    <EventRecordID>1004</EventRecordID>
    <Channel>System</Channel>
    <Computer>LAB-WORKSTATION-01</Computer>
  </System>
  <EventData>
    <Data Name="ServiceName">SentinelXAgentSvc</Data>
    <Data Name="ImagePath">C:\\Program Files\\SentinelX\\agent.exe</Data>
    <Data Name="ServiceType">user mode service</Data>
  </EventData>
</Event>
"""

SAMPLE_1102_LOG_CLEARED = """
<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">
  <System>
    <Provider Name="Microsoft-Windows-Eventlog" />
    <EventID>1102</EventID>
    <TimeCreated SystemTime="2026-10-21T08:19:00.000000Z" />
    <EventRecordID>1005</EventRecordID>
    <Channel>Security</Channel>
    <Computer>LAB-WORKSTATION-01</Computer>
  </System>
  <EventData>
    <Data Name="SubjectUserName">hacker</Data>
  </EventData>
</Event>
"""

SAMPLE_4740_LOCKOUT = """
<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">
  <System>
    <Provider Name="Microsoft-Windows-Security-Auditing" />
    <EventID>4740</EventID>
    <TimeCreated SystemTime="2026-10-21T08:20:00.000000Z" />
    <EventRecordID>1006</EventRecordID>
    <Channel>Security</Channel>
    <Computer>LAB-WORKSTATION-01</Computer>
  </System>
  <EventData>
    <Data Name="TargetUserName">victim_user</Data>
  </EventData>
</Event>
"""

SAMPLE_1116_DEFENDER = """
<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">
  <System>
    <Provider Name="Microsoft-Windows-Windows Defender" />
    <EventID>1116</EventID>
    <TimeCreated SystemTime="2026-10-21T08:21:00.000000Z" />
    <EventRecordID>1007</EventRecordID>
    <Channel>Microsoft-Windows-Windows Defender/Operational</Channel>
    <Computer>LAB-WORKSTATION-01</Computer>
  </System>
  <EventData>
    <Data Name="Threat Name">Trojan:Win32/Wacatac</Data>
    <Data Name="Path">C:\\Users\\alice\\Downloads\\malware.exe</Data>
  </EventData>
</Event>
"""


def test_parse_4624_logon_success():
    res = parse_event_xml(SAMPLE_4624_LOGON_SUCCESS)
    assert res is not None
    assert res["event_type"] == "logon_success"
    assert res["source_type"] == "windows"
    assert "alice" in res["user"]
    assert res["host"] == "LAB-WORKSTATION-01"
    assert res["ip"] == "192.168.1.100"
    assert "Successful logon" in res["message"]


def test_parse_4625_logon_failure():
    res = parse_event_xml(SAMPLE_4625_LOGON_FAILURE)
    assert res is not None
    assert res["event_type"] == "logon_failure"
    assert res["source_type"] == "windows"
    assert "bob" in res["user"]
    assert res["ip"] == "10.0.0.50"
    assert res["severity_hint"] == "medium"
    assert "Failed logon attempt" in res["message"]


def test_parse_4688_process_create():
    res = parse_event_xml(SAMPLE_4688_PROCESS_CREATE)
    assert res is not None
    assert res["event_type"] == "process_create"
    assert "cmd.exe" in res["process"]
    assert "whoami" in res["raw"]["command_line"]
    assert "Process created: cmd.exe" in res["message"]


def test_parse_7045_service_install():
    res = parse_event_xml(SAMPLE_7045_SERVICE_INSTALL)
    assert res is not None
    assert res["event_type"] == "service_install"
    assert "SentinelXAgentSvc" in res["message"]


def test_parse_1102_log_cleared():
    res = parse_event_xml(SAMPLE_1102_LOG_CLEARED)
    assert res is not None
    assert res["event_type"] == "log_cleared"
    assert res["severity_hint"] == "high"
    assert "Security audit log cleared" in res["message"]


def test_parse_4740_account_lockout():
    res = parse_event_xml(SAMPLE_4740_LOCKOUT)
    assert res is not None
    assert res["event_type"] == "account_lockout"
    assert res["severity_hint"] == "high"


def test_parse_1116_defender_detection():
    res = parse_event_xml(SAMPLE_1116_DEFENDER)
    assert res is not None
    assert res["event_type"] == "ids_alert"
    assert res["severity_hint"] == "high"
    assert "Trojan:Win32/Wacatac" in res["message"]


def test_parse_invalid_xml():
    assert parse_event_xml("not valid xml") is None
    assert parse_event_xml("<root></root>") is None
