"""Shared pytest fixtures. See docs/TEST-STRATEGY.md for the four-tier pyramid.

Unit tests (default) need no I/O. Integration tests are marked `integration` and
spin up Postgres/Qdrant/Redis via compose or testcontainers; they are skipped
until the M0 code they exercise exists.
"""

from __future__ import annotations
