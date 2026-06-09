"""Cross-tenant leakage test — non-negotiable (docs/ARCHITECTURE.md §6).

Seeds two tenants, queries across them, and asserts ZERO cross-tenant results.
This is a required, build-blocking CI check once M0/M4 retrieval exists. Skipped
until then so the suite is green during scaffolding.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(reason="needs M0 retrieval + M4 multi-tenancy; becomes a blocking CI check")
def test_no_cross_tenant_results() -> None:
    # 1. seed tenant A and tenant B with distinct corpora
    # 2. issue tenant A's query with tenant=A
    # 3. assert no result belongs to tenant B
    raise AssertionError("unimplemented guard — must be green before any multi-tenant release")
