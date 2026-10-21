from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import List, Optional
from relaypulse.models import WebhookEvent, EventStatus, DLQEntry


class SQLiteEventStore:
    def __init__(self, db_path: Path = Path("relaypulse.db")):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._get_connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS webhook_events (
                    id TEXT PRIMARY KEY,
                    destination_url TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    secret TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_retries INTEGER NOT NULL DEFAULT 5,
                    next_retry_at REAL NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    last_error TEXT,
                    last_status_code INTEGER,
                    idempotency_key TEXT
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_status_retry ON webhook_events(status, next_retry_at);")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_idempotency ON webhook_events(idempotency_key) WHERE idempotency_key IS NOT NULL;")
            conn.commit()

    def save_event(self, event: WebhookEvent) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO webhook_events (
                    id, destination_url, payload, secret, status, attempts,
                    max_retries, next_retry_at, created_at, updated_at,
                    last_error, last_status_code, idempotency_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.destination_url,
                    json.dumps(event.payload),
                    event.secret,
                    event.status.value,
                    event.attempts,
                    event.max_retries,
                    event.next_retry_at,
                    event.created_at,
                    event.updated_at,
                    event.last_error,
                    event.last_status_code,
                    event.idempotency_key
                )
            )
            conn.commit()

    def get_by_idempotency_key(self, idempotency_key: str) -> Optional[WebhookEvent]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM webhook_events WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
            if not row:
                return None
            return self._row_to_event(row)

    def claim_event_for_delivery(self, event_id: str) -> bool:
        """Atomically transitions an event from PENDING/RETRYING to DELIVERING to prevent race conditions."""
        now = time.time()
        with self._get_connection() as conn:
            cur = conn.execute(
                """
                UPDATE webhook_events
                SET status = ?, updated_at = ?
                WHERE id = ? AND (status = ? OR status = ?)
                """,
                (EventStatus.DELIVERING.value, now, event_id, EventStatus.PENDING.value, EventStatus.RETRYING.value)
            )
            conn.commit()
            return cur.rowcount > 0

    def get_event(self, event_id: str) -> Optional[WebhookEvent]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM webhook_events WHERE id = ?", (event_id,)).fetchone()
            if not row:
                return None
            return self._row_to_event(row)

    def get_pending_events(self, limit: int = 50) -> List[WebhookEvent]:
        now = time.time()
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM webhook_events
                WHERE (status = ? OR status = ?) AND next_retry_at <= ?
                ORDER BY next_retry_at ASC LIMIT ?
                """,
                (EventStatus.PENDING.value, EventStatus.RETRYING.value, now, limit)
            ).fetchall()
            return [self._row_to_event(r) for r in rows]

    def update_event_status(
        self,
        event_id: str,
        status: EventStatus,
        attempts: int,
        next_retry_at: float,
        last_error: Optional[str] = None,
        last_status_code: Optional[int] = None
    ) -> None:
        now = time.time()
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE webhook_events
                SET status = ?, attempts = ?, next_retry_at = ?,
                    last_error = ?, last_status_code = ?, updated_at = ?
                WHERE id = ?
                """,
                (status.value, attempts, next_retry_at, last_error, last_status_code, now, event_id)
            )
            conn.commit()

    def list_events(self, status: Optional[EventStatus] = None, limit: int = 50) -> List[WebhookEvent]:
        with self._get_connection() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM webhook_events WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                    (status.value, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM webhook_events ORDER BY created_at DESC LIMIT ?",
                    (limit,)
                ).fetchall()
            return [self._row_to_event(r) for r in rows]

    def list_dlq(self, limit: int = 50) -> List[DLQEntry]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM webhook_events WHERE status = ? ORDER BY updated_at DESC LIMIT ?",
                (EventStatus.DLQ.value, limit)
            ).fetchall()
            return [
                DLQEntry(
                    event_id=r["id"],
                    destination_url=r["destination_url"],
                    payload=json.loads(r["payload"]),
                    attempts=r["attempts"],
                    last_error=r["last_error"],
                    last_status_code=r["last_status_code"],
                    failed_at=r["updated_at"]
                )
                for r in rows
            ]

    def replay_dlq_event(self, event_id: str) -> bool:
        now = time.time()
        with self._get_connection() as conn:
            cur = conn.execute(
                """
                UPDATE webhook_events
                SET status = ?, attempts = 0, next_retry_at = ?, updated_at = ?, last_error = NULL
                WHERE id = ? AND status = ?
                """,
                (EventStatus.PENDING.value, now, now, event_id, EventStatus.DLQ.value)
            )
            conn.commit()
            return cur.rowcount > 0

    def _row_to_event(self, row: sqlite3.Row) -> WebhookEvent:
        keys = row.keys()
        return WebhookEvent(
            id=row["id"],
            destination_url=row["destination_url"],
            payload=json.loads(row["payload"]),
            secret=row["secret"],
            status=EventStatus(row["status"]),
            attempts=row["attempts"],
            max_retries=row["max_retries"],
            next_retry_at=row["next_retry_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_error=row["last_error"],
            last_status_code=row["last_status_code"],
            idempotency_key=row["idempotency_key"] if "idempotency_key" in keys else None
        )
