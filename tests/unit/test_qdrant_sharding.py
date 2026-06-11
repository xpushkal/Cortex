"""Qdrant shard-by-tenant config (M4)."""

from __future__ import annotations

from typing import Any

from cortex.storage.qdrant import DEFAULT_SHARDS, ensure_collection


class _FakeQdrant:
    def __init__(self, *, exists: bool) -> None:
        self._exists = exists
        self.created: dict[str, Any] | None = None

    async def collection_exists(self, name: str) -> bool:
        return self._exists

    async def create_collection(self, **kwargs: Any) -> None:
        self.created = kwargs


async def test_shard_number_is_forwarded_on_create() -> None:
    fake = _FakeQdrant(exists=False)
    await ensure_collection(fake, dim=384, shard_number=6)  # type: ignore[arg-type]
    assert fake.created is not None
    assert fake.created["shard_number"] == 6


async def test_defaults_to_configured_shard_count() -> None:
    fake = _FakeQdrant(exists=False)
    await ensure_collection(fake, dim=384)  # type: ignore[arg-type]
    assert fake.created is not None
    assert fake.created["shard_number"] == DEFAULT_SHARDS


async def test_existing_collection_is_not_recreated() -> None:
    fake = _FakeQdrant(exists=True)
    await ensure_collection(fake, dim=384, shard_number=8)  # type: ignore[arg-type]
    assert fake.created is None
