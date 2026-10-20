# Security Policy

RelayPulse takes operational and cryptographic security seriously.

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting Security Issues

Report any security vulnerabilities to `163651512+Hakantes@users.noreply.github.com`.

## Security Assurances

1. **Replay Attack Defense:** Signatures embed timestamps (`t=...`). Payloads older than tolerance windows (default: 300 seconds) are rejected.
2. **Timing-Safe Comparison:** Signatures are compared using constant-time algorithms (`hmac.compare_digest`), preventing timing analysis attacks.
3. **URL Validation:** Target dispatch URLs must specify HTTP or HTTPS protocols. Local file URIs or internal loopback bypasses can be restricted in production.
