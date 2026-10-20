"""Worker jobs for the approval execution path (P19).

`execute_approved_action_job(ctx, approval_id)` runs AFTER the approve
endpoint commits: the endpoint enqueues it as a post-commit follow-up
(the enqueue-failure path executes inline in the request, see
approvals.py). The job re-checks the approval under a row lock in ITS
own session -- pending, rejected and expired approvals never execute,
and a duplicate job (two workers) sees executed_at already stamped and
refuses.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

logger = logging.getLogger("sentinelx.approvals")


async def execute_approved_action_job(ctx: dict[str, Any], *, approval_id: str) -> dict[str, Any]:
    from app.ai.policy import execute_approved_action
    from app.database import AsyncSessionLocal

    try:
        approval_uuid = uuid.UUID(approval_id)
    except ValueError:
        logger.warning("approvals: execution job got a non-UUID approval_id %r -- dropping", approval_id)
        return {"status": "dropped"}

    async with AsyncSessionLocal() as db:
        outcome = await execute_approved_action(db, approval_uuid, origin="worker")
        logger.info("approvals: execute %s -> %s", approval_id, outcome.get("status"))
        return outcome
