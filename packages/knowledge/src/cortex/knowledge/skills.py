"""Skills-file export (docs/API.md `/skills`, DATA_MODEL.md §6).

Projects the tenant's process objects into the agent-consumable skills file: a
flattened, freshness-labeled, cited view of **active, non-expired** processes
(stale excluded unless asked for). The output is a plain dict that validates
against the `cortex-agent` `SkillsFile` schema — producer and consumer stay
decoupled. Reuses the M2 process registry + M3 freshness.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from cortex.knowledge.repository import get_process_body, list_processes


async def build_skills_file(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    scope: str | None = None,
    include_stale: bool = False,
) -> dict[str, Any]:
    """Build the skills file for a tenant — active, non-expired processes, cited."""
    summaries = await list_processes(session, tenant_id=tenant_id)

    manifest = {"fresh": 0, "stale": 0, "expired": 0}
    for summary in summaries:
        if summary.freshness in manifest:
            manifest[summary.freshness] += 1

    skills: list[dict[str, Any]] = []
    for summary in summaries:
        # Never serve stale/expired knowledge as current (M3): fresh + active by
        # default; stale (which a changed process becomes, as a draft) only when
        # explicitly requested, and always labeled. Expired is never served.
        if summary.freshness == "expired":
            continue
        if summary.freshness == "stale":
            if not include_stale:
                continue
        elif summary.status != "active":
            continue  # a fresh draft pending review is not served by default
        body = await get_process_body(
            session, tenant_id=tenant_id, process_id=uuid.UUID(summary.id)
        )
        if body is None:
            continue
        skills.append(
            {
                "name": body["name"],
                "trigger": body["trigger"],
                "version": body["version"],
                "freshness": summary.freshness,
                "steps": [
                    {
                        "action": step["action"],
                        "actor": step.get("actor"),
                        "decision": step.get("decision"),
                        "citations": step["citations"],
                    }
                    for step in body["steps"]
                ],
            }
        )

    return {
        "tenant": str(tenant_id),
        "scope": scope,
        "generated_at": datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "freshness_manifest": manifest,
        "skills": skills,
    }
