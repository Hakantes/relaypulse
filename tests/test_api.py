import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from relaypulse.api import create_app


def test_api_health_check(tmp_path: Path):
    app = create_app(db_path=tmp_path / "api_test.db")
    client = TestClient(app)

    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "healthy"


def test_api_create_and_list_event(tmp_path: Path):
    app = create_app(db_path=tmp_path / "api_events.db")
    client = TestClient(app)

    # Ingest event
    payload = {
        "destination_url": "https://example.com/receiver",
        "payload": {"user": "alice", "action": "login"},
        "secret": "test_whsec",
        "max_retries": 3
    }
    res = client.post("/v1/events", json=payload)
    assert res.status_code == 202
    data = res.json()
    assert "evt_" in data["id"]
    assert data["status"] == "pending"

    # List events
    list_res = client.get("/v1/events")
    assert list_res.status_code == 200
    events = list_res.json()
    assert len(events) >= 1
    assert events[0]["id"] == data["id"]


def test_api_ssrf_blocked(tmp_path: Path):
    app = create_app(db_path=tmp_path / "api_ssrf.db")
    client = TestClient(app)

    # Cloud metadata URL must be rejected
    payload = {
        "destination_url": "http://169.254.169.254/latest/meta-data/",
        "payload": {"exploit": "attempt"}
    }
    res = client.post("/v1/events", json=payload)
    assert res.status_code == 400
    assert "restricted" in res.json()["detail"].lower()


def test_api_idempotency_duplicate_prevention(tmp_path: Path):
    app = create_app(db_path=tmp_path / "api_idem.db")
    client = TestClient(app)

    payload = {
        "destination_url": "https://example.com/webhook",
        "payload": {"payment_id": "pay_999"},
        "idempotency_key": "idemp_abc_123"
    }

    # First call
    res1 = client.post("/v1/events", json=payload)
    assert res1.status_code == 202
    id1 = res1.json()["id"]

    # Second call with identical idempotency_key
    res2 = client.post("/v1/events", json=payload)
    assert res2.status_code == 202
    id2 = res2.json()["id"]

    # Must return identical event without creating a new duplicate
    assert id1 == id2
