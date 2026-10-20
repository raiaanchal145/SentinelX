"""
The tool registry's shared vocabulary (P19 response actions).

A `ToolSpec` is one entry in the catalogue: what the tool is called,
what it does, how dangerous it is, which module gates it, what it
accepts, WHAT EXECUTORS (actor kinds) may call it, and the code that
actually does the work. The registry is the single source of truth the
policy engine (app/ai/policy.py) reads -- nothing here has a way to run
that bypasses the engine, because `run_tool_call()` is the only thing
that invokes `executor` in this codebase and it is always gated on
`authorize_tool_call()` first.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from pydantic import BaseModel

from app.models import ActorType, ApprovalRiskLevel
from app.scope import Scope


class ToolError(Exception):
    """An executor refused its arguments INSIDE the registered shape
    (unknown id, missing prerequisite). The call already passed the
    policy gate -- this is an execution failure, not a permission one,
    so it is reported in the tool_call_logs result rather than denied."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(code)


@dataclass(frozen=True)
class ToolActor:
    """Who/what is attempting the call, in the engine's terms.

    `kind` is the string matched against the tool's allowed_executors:
    "ai_agent" for an AI agent, or the caller's role value
    (soc_analyst, security_manager, it_developer, auditor,
    organization_admin, platform_soc_analyst) for a human. super_admin
    has a kind too -- it simply is never in any tool's
    allowed_executors, so the registry fails closed against it."""

    actor_type: ActorType
    actor_id: uuid.UUID | None
    kind: str
    role: str | None = None
    scope: Scope | None = None
    organization_id: uuid.UUID | None = None


@dataclass(frozen=True)
class Decision:
    """What the policy engine decided, with the reason it will be
    logged under. verdict is one of "allow" | "needs_approval" | "deny".
    tool_call_logs.decision stores verdict verbatim, deny_reason /
    request reason stores `reason`."""

    verdict: str
    reason: str | None = None


@dataclass
class ToolContext:
    """Everything an executor may need, resolved by the service layer
    BEFORE the policy engine runs: the organization row, the org's
    settings row (None = all flags off) and the optional incident the
    call is about (already verified to belong to the organization)."""

    db: Any  # AsyncSession
    actor: ToolActor
    organization: Any  # Organization row
    settings: Any | None  # OrganizationSettings row or None
    incident: Any | None = None  # Incident row or None


ToolExecutor = Callable[[ToolContext, BaseModel], Awaitable[dict]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    risk_level: ApprovalRiskLevel
    # ModuleKey.value -- the capability that gates the tool at the org
    # level AND in the caller's effective access.
    required_module: str
    # JSON-schema-ish description for the docs and the approval UI's
    # payload preview. Validation itself is by the tool's Args model.
    input_schema: dict
    # Executor kinds that may attempt this tool (see ToolActor.kind).
    allowed_executors: tuple[str, ...]
    args_model: type[BaseModel]
    executor: ToolExecutor


_REGISTRY: dict[str, ToolSpec] = {}


def register(spec: ToolSpec) -> ToolSpec:
    if spec.name in _REGISTRY:
        raise ValueError(f"tool {spec.name} registered twice")
    _REGISTRY[spec.name] = spec
    return spec


def get_tool(name: str) -> ToolSpec | None:
    return _REGISTRY.get(name)


def all_tools() -> list[ToolSpec]:
    return sorted(_REGISTRY.values(), key=lambda t: t.name)


def catalogue() -> list[dict]:
    """A stable, serialisable view of the registry (docs, UI pickers)."""
    return [
        {
            "name": t.name,
            "description": t.description,
            "risk_level": t.risk_level.value,
            "required_module": t.required_module,
            "input_schema": t.input_schema,
            "allowed_executors": list(t.allowed_executors),
        }
        for t in all_tools()
    ]


def canonical_arguments(args: dict) -> str:
    """The value hashed into tool_call_logs.arguments_hash: canonical
    JSON (sorted keys, no whitespace) of the validated arguments. Two
    dicts that mean the same thing always hash the same."""

    def _default(o: Any) -> Any:
        if isinstance(o, BaseModel):
            return o.model_dump()
        raise TypeError(f"not JSON-serialisable: {type(o)}")

    return json.dumps(args, sort_keys=True, separators=(",", ":"), default=_default)
