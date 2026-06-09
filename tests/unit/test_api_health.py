"""The serving skeleton is deployable: liveness/readiness respond."""

from __future__ import annotations

from fastapi.testclient import TestClient

from cortex.api.main import app

client = TestClient(app)


def test_healthz_ok() -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_readyz_reports_env() -> None:
    resp = client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"
