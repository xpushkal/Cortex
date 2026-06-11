"""`POST /v1/ask` — grounded Q&A (docs/API.md).

Hybrid-retrieve → if a relevant active process exists, ground the answer in it
(its cited steps, listed in `used_processes`); otherwise fall back to raw chunk
retrieval. Every answer carries `citations` and `freshness`.

Generation is **extractive by default** — the answer is composed from the
cited step actions / top chunk texts, so it is grounded and offline. Fluent
prose is `CORTEX_ASK=llm` (claude, the `llm` extra), grounded in the same
context; never the CI path.
"""

from __future__ import annotations

import os
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.api.deps import db_session, tenant_id
from cortex.knowledge import match_process
from cortex.obs import get_tracer
from cortex.retrieval import get_embedder, get_reranker, hybrid_search
from cortex.storage import get_qdrant

router = APIRouter()
_tracer = get_tracer(__name__)
_ASK_MODEL = "claude-opus-4-8"


class AskRequest(BaseModel):
    q: str = Field(min_length=1)
    max_context: int = Field(default=8, ge=1, le=50)
    source_kinds: list[str] | None = None


class CitationOut(BaseModel):
    chunk_id: str
    quote: str | None = None
    source_kind: str | None = None
    artifact_id: str | None = None


class AskResponse(BaseModel):
    answer: str
    citations: list[CitationOut]
    freshness: dict[str, Any]
    used_processes: list[str]


def _compose(question: str, context: list[str]) -> str:
    """Compose the answer from grounding context. Extractive default; LLM on flag."""
    if (os.environ.get("CORTEX_ASK", "extractive").lower()) == "llm":
        return _compose_llm(question, context)
    return "\n".join(context)


def _compose_llm(question: str, context: list[str]) -> str:  # pragma: no cover - needs the extra
    try:
        import anthropic
    except ImportError as exc:
        raise RuntimeError("CORTEX_ASK=llm needs the 'llm' extra: uv sync --extra llm") from exc
    joined = "\n\n".join(context)
    response = anthropic.Anthropic().messages.create(
        model=_ASK_MODEL,
        max_tokens=1024,
        thinking={"type": "adaptive"},
        system=(
            "Answer the question using ONLY the provided context. Be concise. "
            "If the context does not contain the answer, say so."
        ),
        messages=[{"role": "user", "content": f"Question: {question}\n\nContext:\n{joined}"}],
    )
    text: str = next(b.text for b in response.content if b.type == "text")
    return text.strip()


@router.post("/v1/ask", response_model=AskResponse)
async def ask(
    req: AskRequest,
    tenant: Annotated[uuid.UUID, Depends(tenant_id)],
    session: Annotated[AsyncSession, Depends(db_session)],
) -> AskResponse:
    with _tracer.start_as_current_span("ask") as span:
        span.set_attribute("cortex.tenant_id", str(tenant))
        hits = await hybrid_search(
            query=req.q,
            tenant_id=tenant,
            session=session,
            qdrant=get_qdrant(),
            embedder=get_embedder(),
            reranker=get_reranker(),
            k=req.max_context,
            source_kinds=req.source_kinds,
        )
        process = await match_process(session, tenant_id=tenant, query=req.q)
        # An expired process is never served as current — fall back to chunks (D6).
        if process is not None and process.get("freshness") == "expired":
            process = None
        span.set_attribute("cortex.grounded_in_process", process is not None)

    if process is not None:
        steps = process["steps"]
        context = [s["action"] for s in steps]
        citations = [
            CitationOut(chunk_id=c["chunk_id"], quote=c.get("quote"))
            for s in steps
            for c in s["citations"]
        ]
        used = [f"process:{process['id']}@v{process['version']}"]
        # Labeled, never hidden: a stale grounding process surfaces as stale.
        state = process.get("freshness", "fresh")
    else:
        context = [h.text for h in hits]
        citations = [
            CitationOut(
                chunk_id=h.chunk_id,
                quote=h.text[:160],
                source_kind=h.source_kind,
                artifact_id=h.artifact_id,
            )
            for h in hits
        ]
        used = []
        state = "fresh"  # re-ingest keeps chunks current; chunk-TTL labeling is future

    return AskResponse(
        answer=_compose(req.q, context),
        citations=citations,
        freshness={"state": state},
        used_processes=used,
    )
