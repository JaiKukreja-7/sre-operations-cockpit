from time import perf_counter
import httpx
from cockpit.models import CheckConfig, DEMO_URL


def probe(config: CheckConfig, client: httpx.Client):
    # Defense in depth: redirects and environment proxies are disabled by callers.
    if config.url != DEMO_URL:
        raise ValueError("Only the configured local demo target is allowed")
    start = perf_counter()
    status = None
    failures = []
    try:
        response = client.get(config.url, timeout=config.timeout_seconds, follow_redirects=False)
        status = response.status_code
        if status != config.expected_status:
            failures.append(f"expected HTTP {config.expected_status}, got {status}")
        if config.required_text not in response.text:
            failures.append("required text missing")
    except httpx.RequestError as exc:
        failures.append(f"network error: {type(exc).__name__}")
    latency = (perf_counter() - start) * 1000
    if latency > config.latency_threshold_ms:
        failures.append(f"latency {latency:.1f} ms exceeds {config.latency_threshold_ms:g} ms")
    return {"http_status": status, "latency_ms": latency,
            "outcome": "BAD" if failures else "GOOD",
            "failure_reason": "; ".join(failures) if failures else None}
