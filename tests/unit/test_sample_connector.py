"""The sample connector must be deterministic — the eval/test corpus depends on it."""

from __future__ import annotations

from cortex.connectors import SampleConnector
from cortex.connectors.base import Connector, Cursor, SourceConfig

CFG = SourceConfig(kind="sample")


def test_implements_connector_protocol() -> None:
    assert isinstance(SampleConnector(), Connector)


def test_backfill_is_stable() -> None:
    a = [r.external_id for r in SampleConnector().backfill(CFG)]
    b = [r.external_id for r in SampleConnector().backfill(CFG)]
    assert a == b
    assert len(a) == len(set(a)) >= 12  # unique, non-trivial corpus


def test_normalize_maps_to_artifact() -> None:
    conn = SampleConnector()
    raw = next(iter(conn.backfill(CFG)))
    art = conn.normalize(raw)
    assert art.source_kind == "sample"
    assert art.external_id == raw.external_id
    assert "refund" in art.content.lower()


def test_poll_yields_nothing_after_backfill() -> None:
    items, _ = SampleConnector().poll(CFG, Cursor())
    assert list(items) == []
