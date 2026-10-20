"""High-risk tools (P19). Risk tier `high`: real-world containment
actions. EVERY call comes back `needs_approval` from the policy engine
-- there is no configuration that lets a high-risk tool run without an
approved, unexpired approval. The executors below are deliberately
thin: they call the device-agent adapter (app/ai/device_agent.py),
which until the device agent milestone ships is the documented mock --
nothing here touches a network, process or filesystem.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from app.ai.device_agent import build_device_adapter
from app.models import ApprovalRiskLevel, Asset
from app.modules import ModuleKey

from .base import ToolContext, ToolError, ToolSpec, register


class _ReasonMixin(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class IsolateHostArgs(_ReasonMixin):
    asset_id: uuid.UUID


class DisableAccountArgs(_ReasonMixin):
    username: str = Field(min_length=1, max_length=200)


class BlockIpArgs(_ReasonMixin):
    ip_address: str = Field(min_length=3, max_length=64)


class KillProcessArgs(_ReasonMixin):
    asset_id: uuid.UUID | None = None
    process: str = Field(min_length=1, max_length=200)


class QuarantineFileArgs(_ReasonMixin):
    asset_id: uuid.UUID | None = None
    path: str = Field(min_length=1, max_length=500)


async def _load_asset(ctx: ToolContext, asset_id: uuid.UUID | None) -> Asset | None:
    if asset_id is None:
        return None
    asset: Asset | None = await ctx.db.get(Asset, asset_id)
    if asset is None or asset.organization_id != ctx.organization.id:
        raise ToolError("asset_not_found", f"No asset {asset_id} in this organization.")
    return asset


async def _isolate_host(ctx: ToolContext, args: IsolateHostArgs) -> dict:
    asset = await _load_asset(ctx, args.asset_id)
    return await build_device_adapter().isolate_host(asset, args.reason)


async def _disable_account(ctx: ToolContext, args: DisableAccountArgs) -> dict:
    return await build_device_adapter().disable_account(args.username, args.reason)


async def _block_ip(ctx: ToolContext, args: BlockIpArgs) -> dict:
    return await build_device_adapter().block_ip(args.ip_address, args.reason)


async def _kill_process(ctx: ToolContext, args: KillProcessArgs) -> dict:
    asset = await _load_asset(ctx, args.asset_id)
    return await build_device_adapter().kill_process(asset, args.process, args.reason)


async def _quarantine_file(ctx: ToolContext, args: QuarantineFileArgs) -> dict:
    asset = await _load_asset(ctx, args.asset_id)
    return await build_device_adapter().quarantine_file(asset, args.path, args.reason)


_register_specs = [
    (
        "host.isolate",
        "Isolate a host from the network (containment). Requires the device agent.",
        IsolateHostArgs,
        _isolate_host,
        "asset_id",
    ),
    (
        "account.disable",
        "Disable a user account (containment). Requires the device agent.",
        DisableAccountArgs,
        _disable_account,
        "username",
    ),
    (
        "ip.block",
        "Block an IP address at the perimeter. Requires the device agent.",
        BlockIpArgs,
        _block_ip,
        "ip_address",
    ),
    (
        "process.kill",
        "Kill a process on a host. Attachment to an asset is recommended; requires the device agent.",
        KillProcessArgs,
        _kill_process,
        "process",
    ),
    (
        "file.quarantine",
        "Quarantine a file on a host. Requires the device agent.",
        QuarantineFileArgs,
        _quarantine_file,
        "path",
    ),
]


for _name, _desc, _model, _fn, _primary_field in _register_specs:
    _schema = _model.model_json_schema()
    # Keep the payload preview honest: mark the primary target parameter.
    _schema["x_primary_target"] = _primary_field
    register(
        ToolSpec(
            name=_name,
            description=_desc,
            risk_level=ApprovalRiskLevel.high,
            required_module=ModuleKey.device_agents.value,
            input_schema=_schema,
            allowed_executors=(
                "ai_agent",
                "organization_admin",
                "security_manager",
                "soc_analyst",
                "platform_soc_analyst",
            ),
            args_model=_model,
            executor=_fn,
        )
    )
