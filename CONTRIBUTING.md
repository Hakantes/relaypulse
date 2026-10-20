# Contributing to RelayPulse

Thank you for contributing to RelayPulse!

## Local Development Setup

1. Clone repo:
   ```bash
   git clone https://github.com/Hakantes/relaypulse.git
   cd relaypulse
   ```
2. Virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   pip install -e ".[dev]"
   ```
3. Run tests:
   ```bash
   pytest -v
   ```

## Design Standards

- All database operations must be transactional and use parameter binding (`?`) to prevent SQL injection.
- HMAC signatures must always be verified with `hmac.compare_digest()`.
- HTTP dispatches must enforce explicit timeouts (default 5.0s) and catch network anomalies cleanly.
