from __future__ import annotations

import time
from urllib.parse import urlparse
from typing import Dict
from relaypulse.models import CircuitState


class DestinationCircuit:
    def __init__(self, failure_threshold: int = 5, cooldown_seconds: float = 30.0):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.state: CircuitState = CircuitState.CLOSED
        self.failure_count: int = 0
        self.last_state_change: float = time.time()
        self.last_failure_time: float = 0.0

    def can_dispatch(self) -> bool:
        now = time.time()
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            # Check if cooldown window has expired
            if now - self.last_state_change >= self.cooldown_seconds:
                self.state = CircuitState.HALF_OPEN
                self.last_state_change = now
                return True
            return False

        if self.state == CircuitState.HALF_OPEN:
            # Allow limited trial probe
            return True

        return True

    def record_success(self) -> None:
        self.failure_count = 0
        if self.state != CircuitState.CLOSED:
            self.state = CircuitState.CLOSED
            self.last_state_change = time.time()

    def record_failure(self) -> None:
        now = time.time()
        self.failure_count += 1
        self.last_failure_time = now

        if self.state == CircuitState.HALF_OPEN or self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            self.last_state_change = now


class CircuitBreakerManager:
    def __init__(self, failure_threshold: int = 5, cooldown_seconds: float = 30.0):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._circuits: Dict[str, DestinationCircuit] = {}

    def _get_host(self, url: str) -> str:
        try:
            return urlparse(url).netloc or url
        except Exception:
            return url

    def get_circuit(self, url: str) -> DestinationCircuit:
        host = self._get_host(url)
        if host not in self._circuits:
            self._circuits[host] = DestinationCircuit(
                failure_threshold=self.failure_threshold,
                cooldown_seconds=self.cooldown_seconds
            )
        return self._circuits[host]

    def can_dispatch(self, url: str) -> bool:
        return self.get_circuit(url).can_dispatch()

    def record_success(self, url: str) -> None:
        self.get_circuit(url).record_success()

    def record_failure(self, url: str) -> None:
        self.get_circuit(url).record_failure()
