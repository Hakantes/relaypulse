from __future__ import annotations

import uuid
from pathlib import Path
from typing import List, Optional
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse

from relaypulse import __version__
from relaypulse.models import (
    WebhookEvent,
    CreateEventRequest,
    EventResponse,
    EventStatus,
    DLQEntry
)
from relaypulse.storage import SQLiteEventStore
from relaypulse.validator import validate_destination_url


def create_app(db_path: Optional[Path] = None) -> FastAPI:
    app = FastAPI(
        title="RelayPulse Webhook Control Plane",
        description="Resilient webhook dispatcher, retry engine, and dead-letter queue management API.",
        version=__version__
    )
    store = SQLiteEventStore(db_path or Path("relaypulse.db"))

    @app.get("/health", tags=["Health"])
    async def health_check():
        return {
            "status": "healthy",
            "service": "relaypulse",
            "version": __version__
        }

    @app.post("/v1/events", response_model=EventResponse, status_code=status.HTTP_202_ACCEPTED, tags=["Events"])
    async def create_event(req: CreateEventRequest):
        # 1. SSRF & Scheme Validation
        is_valid_url, err = validate_destination_url(req.destination_url)
        if not is_valid_url:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err)

        # 2. Idempotency Check
        if req.idempotency_key:
            existing = store.get_by_idempotency_key(req.idempotency_key)
            if existing:
                return EventResponse(
                    id=existing.id,
                    destination_url=existing.destination_url,
                    payload=existing.payload,
                    status=existing.status,
                    attempts=existing.attempts,
                    max_retries=existing.max_retries,
                    created_at=existing.created_at,
                    updated_at=existing.updated_at,
                    last_error=existing.last_error,
                    last_status_code=existing.last_status_code,
                    idempotency_key=existing.idempotency_key
                )

        event_id = f"evt_{uuid.uuid4().hex[:12]}"
        event = WebhookEvent(
            id=event_id,
            destination_url=req.destination_url,
            payload=req.payload,
            secret=req.secret or "default_secret",
            max_retries=req.max_retries,
            idempotency_key=req.idempotency_key,
            status=EventStatus.PENDING
        )
        store.save_event(event)

        return EventResponse(
            id=event.id,
            destination_url=event.destination_url,
            payload=event.payload,
            status=event.status,
            attempts=event.attempts,
            max_retries=event.max_retries,
            created_at=event.created_at,
            updated_at=event.updated_at,
            idempotency_key=event.idempotency_key
        )

    @app.get("/v1/events", response_model=List[EventResponse], tags=["Events"])
    async def list_events(status_filter: Optional[EventStatus] = None, limit: int = 50):
        events = store.list_events(status=status_filter, limit=limit)
        return [
            EventResponse(
                id=e.id,
                destination_url=e.destination_url,
                payload=e.payload,
                status=e.status,
                attempts=e.attempts,
                max_retries=e.max_retries,
                created_at=e.created_at,
                updated_at=e.updated_at,
                last_error=e.last_error,
                last_status_code=e.last_status_code
            )
            for e in events
        ]

    @app.get("/v1/events/{event_id}", response_model=EventResponse, tags=["Events"])
    async def get_event(event_id: str):
        ev = store.get_event(event_id)
        if not ev:
            raise HTTPException(status_code=404, detail=f"Event '{event_id}' not found")
        return EventResponse(
            id=ev.id,
            destination_url=ev.destination_url,
            payload=ev.payload,
            status=ev.status,
            attempts=ev.attempts,
            max_retries=ev.max_retries,
            created_at=ev.created_at,
            updated_at=ev.updated_at,
            last_error=ev.last_error,
            last_status_code=ev.last_status_code
        )

    @app.get("/v1/dlq", response_model=List[DLQEntry], tags=["Dead-Letter Queue"])
    async def list_dlq(limit: int = 50):
        return store.list_dlq(limit=limit)

    @app.post("/v1/dlq/{event_id}/replay", tags=["Dead-Letter Queue"])
    async def replay_dlq_event(event_id: str):
        success = store.replay_dlq_event(event_id)
        if not success:
            raise HTTPException(status_code=400, detail=f"Event '{event_id}' is not in DLQ or does not exist")
        return {"status": "requeued", "event_id": event_id}

    return app
