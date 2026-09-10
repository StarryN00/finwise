from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture()
def app(tmp_path: Path):
    settings = Settings(root=Path(__file__).resolve().parents[1], database_path=tmp_path / "finwise.db", storage_path=tmp_path / "artifacts", require_auth=False)
    return create_app(settings)


@pytest.fixture()
def client(app):
    return TestClient(app)


@pytest.fixture()
def scope():
    return {"tenant_id": "tenant-a", "organization_id": "org-a", "legal_entity_id": "legal-a", "ledger_id": "ledger-a", "accounting_period_id": "2026-03", "baseline_id": "baseline-a-2026-03"}


def command(client, scope, action, target_id, target_version, key, payload=None, role="accountant"):
    return client.post("/api/v1/commands", headers={"X-Actor-Id": "alice", "X-Role": role}, json={"action": action, "target_id": target_id, "target_version": target_version, "scope": scope, "idempotency_key": key, "payload": payload or {}})
