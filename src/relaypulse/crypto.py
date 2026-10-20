from __future__ import annotations

import hashlib
import hmac
import time
from typing import Optional, Tuple


def generate_signature(
    payload_bytes: bytes,
    secret: str,
    timestamp: Optional[int] = None
) -> Tuple[str, int]:
    """
    Generates a timestamped HMAC-SHA256 signature header:
    X-RelayPulse-Signature: t=1729471200,v1=9a8b7c...
    """
    ts = timestamp if timestamp is not None else int(time.time())
    to_sign = f"{ts}.".encode("utf-8") + payload_bytes
    signature = hmac.new(
        key=secret.encode("utf-8"),
        msg=to_sign,
        digestmod=hashlib.sha256
    ).hexdigest()

    header_val = f"t={ts},v1={signature}"
    return header_val, ts


def verify_signature(
    payload_bytes: bytes,
    header_val: str,
    secret: str,
    tolerance_seconds: int = 300
) -> Tuple[bool, Optional[str]]:
    """
    Verifies a timestamped HMAC-SHA256 signature in constant time.
    Returns: (is_valid, error_reason)
    """
    if not header_val:
        return False, "Missing signature header"

    parts = dict(item.split("=", 1) for item in header_val.split(",") if "=" in item)
    ts_str = parts.get("t")
    v1_sig = parts.get("v1")

    if not ts_str or not v1_sig:
        return False, "Malformed signature header (expected t=...,v1=...)"

    try:
        ts = int(ts_str)
    except ValueError:
        return False, "Non-integer timestamp in signature header"

    # Verify timestamp within tolerance window (protects against replay attacks)
    current_time = int(time.time())
    if abs(current_time - ts) > tolerance_seconds:
        return False, f"Timestamp drift ({abs(current_time - ts)}s) exceeded tolerance ({tolerance_seconds}s)"

    # Compute expected signature
    to_sign = f"{ts}.".encode("utf-8") + payload_bytes
    expected_sig = hmac.new(
        key=secret.encode("utf-8"),
        msg=to_sign,
        digestmod=hashlib.sha256
    ).hexdigest()

    # Timing-safe comparison to prevent timing attacks
    if not hmac.compare_digest(v1_sig, expected_sig):
        return False, "HMAC signature mismatch"

    return True, None
