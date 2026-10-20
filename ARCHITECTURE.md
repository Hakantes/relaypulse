# RelayPulse Architecture

## Architectural Purpose

RelayPulse is an asynchronous webhook dispatcher, retry engine, and dead-letter queue (DLQ) control plane designed to eliminate webhook delivery timeouts, mitigate destination DDoS during subscriber outages, and make poison messages easy to diagnose and replay.

```
+-----------------------------------------------------------------------+
|                         SaaS Application Core                         |
|             (Emits billing.paid, user.created, invoice.failed)        |
+-----------------------------------+-----------------------------------+
                                    |
                    POST /v1/events (FastAPI Ingestion)
                                    |
                                    v
+-----------------------------------------------------------------------+
|                    HMAC-SHA256 Signer (crypto.py)                     |
|   - Computes X-RelayPulse-Signature using shared webhook secret       |
|   - Formats timestamped signature header: t=1729471200,v1=sha256...   |
+-----------------------------------+-----------------------------------+
                                    |
                                    v
+-----------------------------------------------------------------------+
|                  Durable Event Store (storage.py)                     |
|   - SQLite in Write-Ahead-Log (WAL) mode                              |
|   - Atomic state transitions: PENDING -> DELIVERING -> SUCCESS / DLQ  |
+-----------------------------------+-----------------------------------+
                                    |
                                    v
+-----------------------------------------------------------------------+
|                 Async Dispatch Worker (dispatcher.py)                 |
|   - Queries pending deliveries                                        |
|   - Evaluates per-destination Circuit Breaker                         |
+-----------------------------------+-----------------------------------+
                                    |
        +---------------------------+---------------------------+
        |                                                       |
        | [Circuit CLOSED]                                      | [Circuit OPEN]
        v                                                       v
+-------------------------------+                       +-------------------------------+
|     HTTP Client Dispatch      |                       |    Temporary Pause / Defer    |
|   - Sends signed payload      |                       |  - Protects subscriber outage |
|   - Strict HTTP timeout (5s)  |                       |  - Retries on cooldown reset  |
+---------------+---------------+                       +-------------------------------+
                |
     +----------+----------+
     |                     |
     v [2xx OK]            v [4xx/5xx or Timeout]
+---------------+   +-------------------------------------------+
| State: SUCCESS|   |           Retry Scheduler Engine          |
+---------------+   | - Exponential backoff + random jitter     |
                    |   T = min(base * 2^attempt + jitter, max) |
                    | - Increments destination failure count    |
                    +---------------------+---------------------+
                                          |
                               [Attempts >= Max (5)]
                                          |
                                          v
                    +-------------------------------------------+
                    |       Dead-Letter Queue (DLQ Ledger)      |
                    | - Captures HTTP status, body, traceback   |
                    | - Exposes API/CLI for manual bulk replay  |
                    +-------------------------------------------+
```

## Security & Reliability Principles

1. **Timing-Safe HMAC-SHA256 Signatures:** Prevents replay attacks by pairing UNIX timestamps with HMAC digest signatures (`X-RelayPulse-Signature: t=...,v1=...`). Verified using `hmac.compare_digest` to prevent timing side-channel attacks.
2. **Circuit Breaker per Destination Host:** If a customer's endpoint fails 5 consecutive times, the circuit trips to `OPEN`. Webhooks to other healthy destinations continue dispatching normally, while the failing host is spared from being flooded until the 30-second cooldown resets to `HALF-OPEN`.
3. **Zero-Dependency SQLite Default:** Operates out of the box without requiring Redis, Celery, or external message queues.
