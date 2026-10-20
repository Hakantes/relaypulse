from __future__ import annotations

import time
from enum import Enum
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class EventStatus(str, Enum):
    PENDING = "pending"
    DELIVERING = "delivering"
    SUCCESS = "success"
    RETRYING = "retrying"
    DLQ = "dlq"


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class WebhookEvent(BaseModel):
    id: str
    destination_url: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    secret: str
    status: EventStatus = EventStatus.PENDING
    attempts: int = 0
    max_retries: int = 5
    next_retry_at: float = Field(default_factory=time.time)
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    last_error: Optional[str] = None
    last_status_code: Optional[int] = None


class CreateEventRequest(BaseModel):
    destination_url: str
    payload: Dict[str, Any]
    secret: Optional[str] = Field(default="default_secret", description="HMAC shared secret")
    max_retries: int = 5


class EventResponse(BaseModel):
    id: str
    destination_url: str
    payload: Dict[str, Any]
    status: EventStatus
    attempts: int
    max_retries: int
    created_at: float
    updated_at: float
    last_error: Optional[str] = None
    last_status_code: Optional[int] = None


class DLQEntry(BaseModel):
    event_id: str
    destination_url: str
    payload: Dict[str, Any]
    attempts: int
    last_error: Optional[str] = None
    last_status_code: Optional[int] = None
    failed_at: float
