# RelayPulse ⚡

[![CI Status](https://github.com/Hakantes/relaypulse/actions/workflows/ci.yml/badge.svg)](https://github.com/Hakantes/relaypulse/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.12+](https://img.shields.io/badge/python-3.12%2B-brightgreen.svg)](https://www.python.org/)

**Resilient webhook delivery engine with HMAC-SHA256 signatures, exponential backoff, circuit breaking, and dead-letter queue replay.**

---

## The Problem

Reliable webhook delivery is a core operational requirement for SaaS products (e.g., Stripe, GitHub, Shopify). Yet engineering teams frequently encounter common operational pitfalls:
1. **The Synchronous Delivery Trap:** Disagreeable third-party receivers or slow networks hold HTTP worker threads hostage, triggering cascading timeouts and crashing upstream APIs.
2. **The "Poison Message" Black Box:** When a webhook payload fails repeatedly due to schema bugs or receiver HTTP 500s, messages are dropped silently or endlessly retried in naive loops.
3. **Thundering Herds & Subscriber Overload:** During customer server outages, naive dispatchers hammer the failing receiver with thousands of concurrent retries, exacerbating downtime.

## The Solution: RelayPulse

**RelayPulse** is a lightweight, zero-external-dependency webhook dispatcher and control plane:
- **Asynchronous Non-Blocking Dispatch:** Instantly accepts events (`202 Accepted`) and processes delivery via background workers.
- **Timing-Safe HMAC-SHA256 Signatures:** Cryptographically signs every payload with timestamped headers (`X-RelayPulse-Signature: t=...,v1=...`), preventing tampering and replay attacks.
- **Per-Destination Circuit Breakers:** Automatically detects failing receivers and trips to `OPEN` state, pausing traffic to the struggling subscriber while continuing normal deliveries to healthy endpoints.
- **Exponential Backoff with Full Jitter:** Retries transient failures with randomized jitter ($T = \min(\text{base} \cdot 2^{\text{attempt}} + \text{jitter}, \text{max})$), preventing thundering herds.
- **Durable Embedded Queue:** SQLite Write-Ahead Log (WAL) mode guarantees zero message loss across application restarts without requiring external Redis or Celery clusters.
- **Dead-Letter Queue (DLQ) Control Plane:** Captures failed responses, HTTP status codes, and error traces, with instant one-command replay via REST API or CLI.

---

## Architecture Overview

```
                          +------------------------+
                          |   SaaS Application     |
                          +-----------+------------+
                                      |
                      POST /v1/events (202 Accepted)
                                      |
                                      v
                          +------------------------+
                          |   Durable SQLite WAL   |
                          |  (Zero External Deps)  |
                          +-----------+------------+
                                      |
                                      v
                          +------------------------+
                          |  Async Dispatch Worker |
                          |  - HMAC-SHA256 Signing |
                          |  - Circuit Breaker     |
                          +-----------+------------+
                                      |
                   +------------------+------------------+
                   |                                     |
                   v [2xx Success]                       v [Failures / Outage]
+------------------------------------+ +-------------------------------------+
|        State: SUCCESS              | |   Exponential Backoff + DLQ Routing |
| (Records latency & status code)    | | (Trips circuit, moves to DLQ on max)|
+------------------------------------+ +-----------------+-------------------+
                                                         |
                                                         v
                                       +-------------------------------------+
                                       |       DLQ Replay Control Plane      |
                                       |     (REST API & Terminal CLI)       |
                                       +-------------------------------------+
```

---

## Installation

### From Source (Local Development)
```bash
git clone https://github.com/Hakantes/relaypulse.git
cd relaypulse
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e .
```

---

## Quick-Start Guide

### 1. Launch the Control Plane Daemon
```bash
relaypulse serve --host 127.0.0.1 --port 8443
```

### 2. Ingest a Webhook Event via REST API
```bash
curl -X POST http://127.0.0.1:8443/v1/events \
  -H "Content-Type: application/json" \
  -d '{
    "destination_url": "https://webhook.site/sample",
    "payload": {"event": "invoice.paid", "amount": 4900, "currency": "usd"},
    "secret": "whsec_live_top_secret_key"
  }'
```

### 3. Dispatch an Event Immediately via CLI
```bash
relaypulse send \
  --url "https://httpbin.org/post" \
  --payload '{"user": "alice", "tier": "enterprise"}' \
  --secret "my_secret_token"
```

### 4. Inspect Dead-Letter Queue (DLQ)
```bash
relaypulse dlq list
```

### 5. Replay a Failed Message
```bash
relaypulse dlq replay evt_3f8a92b0c1
```

### 6. Verify Signature on Receiver Side
```bash
relaypulse verify-sig \
  --payload '{"user": "alice"}' \
  --signature "t=1729471200,v1=9a8b7c..." \
  --secret "my_secret_token"
```

---

## REST API Reference

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/v1/events` | `POST` | Ingest new webhook event (returns 202 Accepted) |
| `/v1/events` | `GET` | List event delivery history and statuses |
| `/v1/events/{id}` | `GET` | Fetch single event details and delivery attempts |
| `/v1/dlq` | `GET` | List messages permanently moved to Dead-Letter Queue |
| `/v1/dlq/{id}/replay` | `POST` | Re-queue a failed DLQ message for immediate delivery |
| `/health` | `GET` | Operational health check endpoint |

---

## Testing

Run unit and integration test suites:
```bash
pytest -v
```

---

## Cryptographic Specification

RelayPulse generates signatures following industry-standard HMAC authentication:
1. Header: `X-RelayPulse-Signature: t={timestamp},v1={hex_digest}`
2. Signed Payload: `{timestamp}.{raw_json_body}`
3. Algorithm: HMAC with SHA-256 (`hashlib.sha256`)
4. Verification: Evaluated via `hmac.compare_digest` in constant time to prevent timing analysis attacks.

---

## Known Limitations

- Embedded SQLite queue is optimized for single-node instances handling up to ~2,000 events/second. Distributed multi-region Redis cluster support is planned for v0.2.0.
- Webhook endpoints must respond within 5 seconds by default; endpoints exceeding this trigger a timeout and exponential retry.

---

## Contributing and License

Contributions are welcome! Please check [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

Distributed under the **MIT License**. See [LICENSE](LICENSE) for details.
