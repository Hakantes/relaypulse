# Changelog

All notable changes to RelayPulse will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-10-21

### Added
- Cryptographic HMAC-SHA256 signature generator and timing-safe signature verifier.
- Embedded SQLite durable queue with WAL mode, parameterized statements, and atomic state transitions.
- Asynchronous dispatch worker engine using `httpx.AsyncClient` with configurable timeout limits.
- Exponential backoff retry scheduler with full random jitter to prevent thundering herd.
- Per-destination circuit breaker (`CLOSED`, `OPEN`, `HALF-OPEN`) protecting failing subscriber endpoints.
- Dead-Letter Queue (DLQ) state ledger capturing HTTP status, headers, and error traces.
- FastAPI REST API providing event ingestion, state inspection, and manual DLQ replay.
- Rich CLI interface (`serve`, `send`, `dlq list`, `dlq replay`, `verify-sig`).
