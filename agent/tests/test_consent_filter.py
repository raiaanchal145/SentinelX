"""
Unit Tests for Consent Category Filtering and XPath Construction.
"""

from agent.collectors.win_events import build_channel_xpath
from agent.schema import is_collector_consented


def test_consent_filter_empty():
    assert build_channel_xpath("Security", set()) is None
    assert build_channel_xpath("System", set()) is None
    assert build_channel_xpath("Microsoft-Windows-Windows Defender/Operational", set()) is None


def test_consent_filter_authentication_only():
    granted = {"authentication"}
    sec_xpath = build_channel_xpath("Security", granted)
    assert sec_xpath is not None
    assert "EventID=4624" in sec_xpath
    assert "EventID=4625" in sec_xpath
    assert "EventID=4740" in sec_xpath
    # process_activity (4688) must NOT be present
    assert "EventID=4688" not in sec_xpath
    # system_integrity (4720) must NOT be present
    assert "EventID=4720" not in sec_xpath

    # System and Defender channels must return None
    assert build_channel_xpath("System", granted) is None
    assert build_channel_xpath("Microsoft-Windows-Windows Defender/Operational", granted) is None


def test_consent_filter_process_activity_only():
    granted = {"process_activity"}
    sec_xpath = build_channel_xpath("Security", granted)
    assert sec_xpath is not None
    assert "EventID=4688" in sec_xpath
    assert "EventID=4624" not in sec_xpath

    sys_xpath = build_channel_xpath("System", granted)
    assert sys_xpath is not None
    assert "EventID=7045" in sys_xpath


def test_consent_filter_defender():
    granted = {"security_defenses"}
    def_xpath = build_channel_xpath("Microsoft-Windows-Windows Defender/Operational", granted)
    assert def_xpath is not None
    assert "EventID=1116" in def_xpath
    assert "EventID=1117" in def_xpath


def test_is_collector_consented():
    granted = {"authentication", "process_activity"}
    assert is_collector_consented(4624, granted) is True
    assert is_collector_consented(4625, granted) is True
    assert is_collector_consented(4688, granted) is True
    # 4720 belongs to system_integrity -> not consented
    assert is_collector_consented(4720, granted) is False
    # 1116 belongs to security_defenses -> not consented
    assert is_collector_consented(1116, granted) is False
