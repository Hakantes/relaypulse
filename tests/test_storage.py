import time
from pathlib import Path
from relaypulse.models import WebhookEvent, EventStatus
from relaypulse.storage import SQLiteEventStore


def test_sqlite_event_lifecycle(tmp_path: Path):
    db_file = tmp_path / "test.db"
    store = SQLiteEventStore(db_file)

    event = WebhookEvent(
        id="evt_test_101",
        destination_url="https://api.example.com/webhook",
        payload={"msg": "ping"},
        secret="test_secret",
        status=EventStatus.PENDING
    )

    store.save_event(event)

    # Fetch back
    fetched = store.get_event("evt_test_101")
    assert fetched is not None
    assert fetched.id == "evt_test_101"
    assert fetched.payload == {"msg": "ping"}
    assert fetched.status == EventStatus.PENDING

    # Check pending list
    pending = store.get_pending_events()
    assert len(pending) == 1
    assert pending[0].id == "evt_test_101"

    # Update status to SUCCESS
    store.update_event_status("evt_test_101", EventStatus.SUCCESS, attempts=1, next_retry_at=0.0, last_status_code=200)
    updated = store.get_event("evt_test_101")
    assert updated.status == EventStatus.SUCCESS
    assert updated.attempts == 1
    assert updated.last_status_code == 200

    # No more pending events
    assert len(store.get_pending_events()) == 0


def test_dlq_and_replay(tmp_path: Path):
    db_file = tmp_path / "test_dlq.db"
    store = SQLiteEventStore(db_file)

    event = WebhookEvent(
        id="evt_dlq_001",
        destination_url="https://broken.endpoint/hook",
        payload={"order_id": 99},
        secret="secret",
        status=EventStatus.DLQ,
        attempts=5,
        last_error="HTTP 500 Internal Server Error",
        last_status_code=500
    )
    store.save_event(event)

    dlq_list = store.list_dlq()
    assert len(dlq_list) == 1
    assert dlq_list[0].event_id == "evt_dlq_001"

    # Replay event
    ok = store.replay_dlq_event("evt_dlq_001")
    assert ok is True

    # Replayed event should be back in PENDING with 0 attempts
    replayed = store.get_event("evt_dlq_001")
    assert replayed.status == EventStatus.PENDING
    assert replayed.attempts == 0
    assert len(store.list_dlq()) == 0
