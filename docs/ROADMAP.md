# Roadmap — Cortex

**Status:** Draft v1

Build order, each milestone with a concrete **done-when** gate. Ship a thin
vertical slice first, then deepen. Every milestone leaves the system runnable.

---

## M0 — Skeleton (vertical slice)
Get one source end-to-end with naive retrieval.

- Infra up via docker-compose (Postgres, Qdrant, Redis, OTel, Grafana).
- `sample` connector + one real connector (Slack or Notion).
- Fixed-size chunk → base BGE embed → Qdrant upsert.
- `/search` returns dense-only results, tenant-filtered.

**Done when:** ingest the sample corpus and `/search` returns relevant chunks for
10 seed queries; one trace visible end-to-end in Grafana.

---

## M1 — Retrieval quality
Make retrieval good and *measured*.

- Source-aware chunking + contextual blurbs.
- BM25 + dense + RRF fusion; cross-encoder rerank.
- Eval harness: retrieval golden set + Recall@k / nDCG@k / MRR.
- Wire the **CI regression gate**.

**Done when:** Recall@10 ≥ 0.85 and nDCG@10 ≥ 0.70 on the held-out golden set, and
a deliberate quality regression fails CI.

---

## M2 — Knowledge structuring
From chunks to structured knowledge.

- Entity + relation extraction → Postgres graph, with provenance.
- Entity resolution (alias merging).
- Process extraction → versioned process objects, every step cited.
- Pydantic validation + faithfulness gate on process steps.
- `/processes` + `/ask` (grounded in processes when available).

**Done when:** process-extraction precision ≥ 0.80 / recall ≥ 0.70 vs the process
golden set, with 100% of shipped steps carrying valid citations.

---

## M3 — Freshness loop
Keep it current.

- Incremental sync (webhooks where available) + idempotent re-ingest.
- Staleness marking on source change; TTL sweep → expired.
- Contradiction detection → new version + review flag.
- Freshness surfaced in `/ask` and `/skills`.

**Done when:** a change to a source artifact is retrievable in < 60 s (webhook
path) and dependent process objects are correctly marked stale; no stale data
served unlabeled.

---

## M4 — Scale & infra
Prove it holds up.

- Multi-tenancy: Qdrant shard-by-tenant, Postgres RLS, mandatory tenant filter.
- Cross-tenant leakage test in CI.
- Ingress + egress rate limiting (per-tenant, per-source token buckets).
- `scripts/load_test.py` (k6/locust); autoscaling on CPU + queue depth.
- Terraform + k8s manifests.

**Done when:** sustained 600 QPS on `/search` at p95 < 200 ms over a 2M-chunk
index; ingestion ≥ 500 docs/min/worker; cross-tenant leakage test green.

---

## M5 — ML depth (embedding fine-tune)
The from-first-principles ML proof.

- Synthetic query generation + hard-negative mining.
- Contrastive fine-tune of BGE (`MultipleNegativesRankingLoss`).
- A/B vs base on held-out golden set; report deltas.

**Done when:** fine-tuned embeddings beat base BGE by ≥ 5% Recall@10 and ≥ 0.03
nDCG@10 on the held-out set, and the model is swapped into serving behind a flag.

---

## M6 — Skills export + agent demo
Close the loop to the YC thesis.

- `/skills` export (active, non-stale processes; freshness manifest; citations).
- A reference agent consumes the skills file and completes a scripted task
  (e.g. correctly routes a $750 refund) grounded entirely in Cortex.

**Done when:** an external agent, given only the skills file, completes the
scripted task with every action traceable to a cited process step.

---

## Stretch (post-v1)
- Rust hot-path for BM25 + RRF fusion (measured latency drop).
- Learned fusion weights per source.
- Neo4j migration if graph traversal depth/volume demands it.
- Per-document ACL mirroring of source permission models.
- Action execution (agents writing back to source systems) behind approval gates.

---

## Suggested resume bullets (fill brackets with measured numbers)

- Built **Cortex**, a YC S26-RFS "Company Brain": a multi-source knowledge system
  that ingests Slack/email/docs/code/tickets and structures them into versioned,
  citeable, agent-executable process objects.
  M2 ships the structuring layer: a provenance-tracked entity/relation graph and
  versioned, faithfulness-gated process objects with **100% valid step citations**
  (blocking CI gate), served via /processes and grounded /ask.
- Engineered async, idempotent, rate-limited ingestion sustaining **[N] docs/min/worker**
  across [k] source connectors with a change-driven freshness loop.
- Built a hybrid retrieval stack (BM25 + dense + cross-encoder rerank) hitting
  **Recall@10 0.95 / nDCG@10 0.91** (held-out golden set, M1 baseline stack),
  guarded by a blocking CI eval-regression gate.
- Fine-tuned domain embeddings (contrastive + hard-negative mining) for **+[Z]%
  Recall@10** over the off-the-shelf baseline.
- Designed multi-tenant infra (sharded vector store, per-tenant/per-source rate
  limiting) load-tested to **[Q] QPS at p95 [L] ms** over a [M]-chunk index.
