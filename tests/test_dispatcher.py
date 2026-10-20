import pytest
from pathlib import Path
import httpx
from relaypulse.models import WebhookEvent, EventStatus
from relaypulse.storage import SQLiteEventStore
from relaypulse.dispatcher import WebhookDispatcher, calculate_backoff


def test_calculate_backoff():
    b0 = calculate_backoff(0)
    b1 = calculate_backoff(1)
    b2 = calculate_backoff(2)
    assert b0 < b1 < b2


@pytest.mark.asyncio
async def test_dispatch_event_success(tmp_path: Path):
    store = SQLiteEventStore(tmp_path / "dispatch_test.db")

    # Mock client using httpx.MockTransport
    def handler(request: httpx.Request):
        assert "X-RelayPulse-Signature" in request.headers
        assert "X-RelayPulse-Event-ID" in request.headers
        return httpx.Response(200, json={"status": "received"})

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    dispatcher = WebhookDispatcher(store=store, custom_client=mock_client)

    event = WebhookEvent(
        id="evt_success_1",
        destination_url="https://subscriber.test/webhook",
        payload={"action": "created"},
        secret="whsec_123"
    )
    store.save_event(event)

    success, code, err = await dispatcher.dispatch_event(event)
    assert success is True
    assert code == 200
    assert err is None

    # Check database record
    saved = store.get_event("evt_success_1")
    assert saved.status == EventStatus.SUCCESS
    assert saved.attempts == 1


@pytest.mark.asyncio
async def test_dispatch_event_failure_moves_to_retry_or_dlq(tmp_path: Path):
    store = SQLiteEventStore(tmp_path / "dispatch_fail_test.db")

    def fail_handler(request: httpx.Request):
        return httpx.Response(500, text="Internal Server Error")

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(fail_handler))
    dispatcher = WebhookDispatcher(store=store, custom_client=mock_client)

    event = WebhookEvent(
        id="evt_fail_1",
        destination_url="https://broken.test/webhook",
        payload={"action": "test"},
        secret="whsec_123",
        attempts=0,
        max_retries=2
    )
    store.save_event(event)

    # First attempt: moves to RETRYING
    success1, code1, _ = await dispatcher.dispatch_event(event)
    assert success1 is False
    assert code1 == 500
    saved1 = store.get_event("evt_fail_1")
    assert saved1.status == EventStatus.RETRYING
    assert saved1.attempts == 1

    # Second attempt: exceeds max_retries (2) -> moves to DLQ
    success2, code2, _ = await dispatcher.dispatch_event(saved1)
    assert success2 is False
    saved2 = store.get_event("evt_fail_1")
    assert saved2.status == EventStatus.DLQ
    assert saved2.attempts == 2
