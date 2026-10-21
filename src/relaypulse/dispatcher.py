from __future__ import annotations

import asyncio
import json
import random
import time
from typing import Optional, Tuple
import httpx

from relaypulse.models import WebhookEvent, EventStatus
from relaypulse.crypto import generate_signature
from relaypulse.storage import SQLiteEventStore
from relaypulse.circuit import CircuitBreakerManager
from relaypulse.validator import validate_destination_url


def calculate_backoff(attempt: int, base_seconds: float = 1.0, max_seconds: float = 120.0) -> float:
    """Computes exponential backoff with random jitter."""
    exp_factor = min(max_seconds, base_seconds * (2 ** min(attempt, 8)))
    jitter = random.uniform(0.1, 0.8)
    return round(exp_factor + jitter, 2)


class WebhookDispatcher:
    def __init__(
        self,
        store: SQLiteEventStore,
        circuit_manager: Optional[CircuitBreakerManager] = None,
        timeout_seconds: float = 5.0,
        custom_client: Optional[httpx.AsyncClient] = None
    ):
        self.store = store
        self.circuit_manager = circuit_manager or CircuitBreakerManager()
        self.timeout_seconds = timeout_seconds
        self._custom_client = custom_client

    async def dispatch_event(self, event: WebhookEvent) -> Tuple[bool, Optional[int], Optional[str]]:
        """Executes delivery of a single webhook event."""
        # 1. SSRF & URL Validation Check
        is_valid, url_err = validate_destination_url(event.destination_url)
        if not is_valid:
            self.store.update_event_status(
                event_id=event.id,
                status=EventStatus.DLQ,
                attempts=event.attempts + 1,
                next_retry_at=0.0,
                last_error=f"Blocked invalid destination URL: {url_err}"
            )
            return False, None, url_err

        # 2. Check Circuit Breaker
        if not self.circuit_manager.can_dispatch(event.destination_url):
            err_msg = f"Circuit breaker is OPEN for destination {event.destination_url}. Delivery paused."
            backoff = calculate_backoff(event.attempts + 1)
            self.store.update_event_status(
                event_id=event.id,
                status=EventStatus.RETRYING,
                attempts=event.attempts,
                next_retry_at=time.time() + backoff,
                last_error=err_msg
            )
            return False, None, err_msg

        # 3. Atomically claim event to prevent concurrent double-delivery race condition
        claimed = self.store.claim_event_for_delivery(event.id)
        if not claimed and event.status != EventStatus.DELIVERING:
            return False, None, "Event already claimed by another worker"

        # 4. Serialize payload and compute signature
        payload_bytes = json.dumps(event.payload).encode("utf-8")
        sig_header, ts = generate_signature(payload_bytes, event.secret)

        headers = {
            "Content-Type": "application/json",
            "X-RelayPulse-Signature": sig_header,
            "X-RelayPulse-Event-ID": event.id,
            "X-RelayPulse-Attempt": str(event.attempts + 1)
        }

        # 3. HTTP Delivery
        client = self._custom_client or httpx.AsyncClient(timeout=self.timeout_seconds)
        try:
            resp = await client.post(event.destination_url, content=payload_bytes, headers=headers)
            new_attempts = event.attempts + 1

            if 200 <= resp.status_code < 300:
                # Delivery Succeeded
                self.circuit_manager.record_success(event.destination_url)
                self.store.update_event_status(
                    event_id=event.id,
                    status=EventStatus.SUCCESS,
                    attempts=new_attempts,
                    next_retry_at=0.0,
                    last_status_code=resp.status_code
                )
                return True, resp.status_code, None
            else:
                # Delivery Failed with HTTP error status
                err_msg = f"Receiver returned HTTP {resp.status_code}: {resp.text[:120]}"
                self._handle_failure(event, new_attempts, err_msg, resp.status_code)
                return False, resp.status_code, err_msg

        except Exception as exc:
            new_attempts = event.attempts + 1
            err_msg = f"Network transport error: {type(exc).__name__} - {str(exc)}"
            self._handle_failure(event, new_attempts, err_msg, None)
            return False, None, err_msg

        finally:
            if not self._custom_client:
                await client.aclose()

    def _handle_failure(
        self,
        event: WebhookEvent,
        new_attempts: int,
        err_msg: str,
        status_code: Optional[int]
    ) -> None:
        self.circuit_manager.record_failure(event.destination_url)

        if new_attempts >= event.max_retries:
            # Exceeded retries: route to Dead-Letter Queue
            self.store.update_event_status(
                event_id=event.id,
                status=EventStatus.DLQ,
                attempts=new_attempts,
                next_retry_at=0.0,
                last_error=err_msg,
                last_status_code=status_code
            )
        else:
            # Schedule next retry with exponential backoff
            backoff = calculate_backoff(new_attempts)
            self.store.update_event_status(
                event_id=event.id,
                status=EventStatus.RETRYING,
                attempts=new_attempts,
                next_retry_at=time.time() + backoff,
                last_error=err_msg,
                last_status_code=status_code
            )

    async def process_pending_batch(self, limit: int = 20) -> int:
        """Fetches and executes pending events due for delivery."""
        pending = self.store.get_pending_events(limit=limit)
        if not pending:
            return 0

        tasks = [self.dispatch_event(ev) for ev in pending]
        await asyncio.gather(*tasks, return_exceptions=True)
        return len(pending)
