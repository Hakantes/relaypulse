import time
from relaypulse.circuit import CircuitBreakerManager
from relaypulse.models import CircuitState


def test_circuit_trips_on_failures():
    mgr = CircuitBreakerManager(failure_threshold=3, cooldown_seconds=0.5)
    url = "https://client.example.com/webhooks"

    assert mgr.can_dispatch(url) is True

    # Record 2 failures -> still closed
    mgr.record_failure(url)
    mgr.record_failure(url)
    assert mgr.get_circuit(url).state == CircuitState.CLOSED
    assert mgr.can_dispatch(url) is True

    # 3rd failure -> trips to OPEN
    mgr.record_failure(url)
    assert mgr.get_circuit(url).state == CircuitState.OPEN
    assert mgr.can_dispatch(url) is False

    # Wait for cooldown to expire -> transitions to HALF_OPEN
    time.sleep(0.6)
    assert mgr.can_dispatch(url) is True
    assert mgr.get_circuit(url).state == CircuitState.HALF_OPEN

    # Success in HALF_OPEN resets to CLOSED
    mgr.record_success(url)
    assert mgr.get_circuit(url).state == CircuitState.CLOSED
    assert mgr.get_circuit(url).failure_count == 0
