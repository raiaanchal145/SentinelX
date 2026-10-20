"""
Mock device agents (P19) -- the adapter every high-risk tool executes
through.

The real response backend is the device agent milestone (the
`device_agents` module key already reserves that plumbing). Until then,
every high-risk tool calls THIS adapter: it performs no side effect
anywhere -- no network, no process, no filesystem -- and returns a
structured result that makes the simulation explicit. The point of the
response-actions milestone is the governance layer: who requested what,
who approved it, that it executed exactly once, and that the whole
story is provable in tool_call_logs + audit_logs. When the device agent
lands, only this file changes (new adapter, same interface).
"""

from __future__ import annotations

from typing import Any, Protocol

from app.models import Asset


class DeviceAgentAdapter(Protocol):
    """One method per high-risk tool. Every method is safe to call
    from a request handler or a worker job: it returns a plain dict."""

    async def isolate_host(self, asset: Asset, reason: str) -> dict: ...

    async def disable_account(self, username: str, reason: str) -> dict: ...

    async def block_ip(self, ip_address: str, reason: str) -> dict: ...

    async def kill_process(self, asset: Asset | None, process: str, reason: str) -> dict: ...

    async def quarantine_file(self, asset: Asset | None, path: str, reason: str) -> dict: ...


def _simulated(action: str, target: str, *, asset_name: str | None = None) -> dict:
    return {
        "status": "simulated",
        "action": action,
        "target": target,
        "asset": asset_name,
        "message": "requires the device agent -- simulated by the mock adapter; no side effect performed",
    }


class MockDeviceAgentAdapter:
    """The dev/test adapter: records the call, changes nothing."""

    async def isolate_host(self, asset: Asset, reason: str) -> dict:
        return _simulated("isolate_host", asset.hostname or asset.name, asset_name=asset.name)

    async def disable_account(self, username: str, reason: str) -> dict:
        return _simulated("disable_account", username)

    async def block_ip(self, ip_address: str, reason: str) -> dict:
        return _simulated("block_ip", ip_address)

    async def kill_process(self, asset: Asset | None, process: str, reason: str) -> dict:
        return _simulated("kill_process", process, asset_name=asset.name if asset else None)

    async def quarantine_file(self, asset: Asset | None, path: str, reason: str) -> dict:
        return _simulated("quarantine_file", path, asset_name=asset.name if asset else None)


def build_device_adapter() -> DeviceAgentAdapter:
    """Factory. The device agent milestone will return a real adapter
    here (config-selected); today there is only one safe choice."""
    return MockDeviceAgentAdapter()
