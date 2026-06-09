"""Idempotent ingestion (docs/INGESTION.md §3): re-ingest unchanged = no-op.

Skipped until the M0 pipeline exists.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(reason="needs M0 ingestion pipeline")
def test_reingest_unchanged_hash_is_noop() -> None:
    raise AssertionError("unimplemented — verify content_hash match short-circuits the pipeline")
