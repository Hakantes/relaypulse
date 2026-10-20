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
