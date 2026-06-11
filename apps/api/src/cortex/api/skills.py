"""`GET /v1/skills` — the agent-consumable skills export (docs/API.md).

Exports the tenant's active, non-expired process objects as the skills file: a
flattened, freshness-labeled, cited projection a reference agent grounds its
actions in (the YC-thesis close, ROADMAP §M6). Stale knowledge is excluded
unless `include_stale=true`, and always labeled.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.api.deps import db_session, tenant_id
from cortex.api.ratelimit import rate_limit
from cortex.knowledge import build_skills_file
from cortex.obs import get_tracer

router = APIRouter()
_tracer = get_tracer(__name__)


@router.get("/v1/skills", dependencies=[Depends(rate_limit("heavy"))])
async def skills_endpoint(
    tenant: Annotated[uuid.UUID, Depends(tenant_id)],
    session: Annotated[AsyncSession, Depends(db_session)],
    scope: Annotated[str | None, Query()] = None,
    include_stale: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    with _tracer.start_as_current_span("skills.export") as span:
        span.set_attribute("cortex.tenant_id", str(tenant))
        skills = await build_skills_file(
            session, tenant_id=tenant, scope=scope, include_stale=include_stale
        )
        span.set_attribute("cortex.skills", len(skills["skills"]))
    return skills
