import time
from relaypulse.crypto import generate_signature, verify_signature


def test_signature_generation_and_verification():
    payload = b'{"event": "charge.succeeded", "amount": 2500}'
    secret = "whsec_test_secret_12345"

    header_val, ts = generate_signature(payload, secret)
    assert header_val.startswith(f"t={ts},v1=")

    # Verify signature passes
    valid, err = verify_signature(payload, header_val, secret)
    assert valid is True
    assert err is None


def test_signature_mismatch_with_wrong_secret():
    payload = b'{"event": "test"}'
    header_val, _ = generate_signature(payload, "secret_A")

    valid, err = verify_signature(payload, header_val, "secret_B")
    assert valid is False
    assert "mismatch" in err


def test_signature_tampered_payload():
    payload = b'{"amount": 100}'
    tampered = b'{"amount": 9999}'
    secret = "whsec_secret"

    header_val, _ = generate_signature(payload, secret)
    valid, err = verify_signature(tampered, header_val, secret)
    assert valid is False
    assert "mismatch" in err


def test_signature_expired_timestamp():
    payload = b'{"event": "test"}'
    secret = "whsec_secret"
    old_timestamp = int(time.time()) - 400  # 400 seconds ago (tolerance is 300)

    header_val, _ = generate_signature(payload, secret, timestamp=old_timestamp)
    valid, err = verify_signature(payload, header_val, secret, tolerance_seconds=300)
    assert valid is False
    assert "exceeded tolerance" in err
