"""Drive the real worker through Healthy -> Slow -> Failing -> Healthy."""
import time
from datetime import datetime
import httpx


def demonstrate(client, timeout=15):
    outcomes = []
    try:
        for mode, expected in (("Healthy", "GOOD"), ("Slow", "BAD"),
                               ("Failing", "BAD"), ("Healthy", "GOOD")):
            response = client.put('/api/demo', json={'mode': mode, 'delay_seconds': .8})
            response.raise_for_status()
            changed = time.time()
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                response = client.get('/api/checks/1/results')
                response.raise_for_status()
                rows = response.json()
                row = next((row for row in reversed(rows)
                            if datetime.fromisoformat(row['scheduled_at']).timestamp() >= changed
                            and row['outcome'] in ('GOOD', 'BAD')), None)
                if row:
                    if row['outcome'] != expected:
                        raise RuntimeError(f"{mode}: expected {expected}, got {row}")
                    if mode == 'Slow' and (row['http_status'] != 200 or 'latency' not in row['failure_reason']):
                        raise RuntimeError(f"Slow did not demonstrate latency failure: {row}")
                    if mode == 'Failing' and row['http_status'] != 500:
                        raise RuntimeError(f"Failing did not return HTTP 500: {row}")
                    print(f"{mode}: {row['outcome']} HTTP {row['http_status']} "
                          f"{row['latency_ms']:.1f} ms; {row['failure_reason'] or 'all assertions passed'}",
                          flush=True)
                    outcomes.append(row)
                    break
                time.sleep(.1)
            else:
                raise RuntimeError(f"No completed probe for {mode}; is the worker running?")
        return outcomes
    finally:
        # Restore the demo even when a validation fails.
        client.put('/api/demo', json={'mode': 'Healthy', 'delay_seconds': 1})


def main():
    with httpx.Client(base_url='http://127.0.0.1:8000', trust_env=False, timeout=3) as client:
        demonstrate(client)
        response = client.get('/api/checks/1/summary')
        response.raise_for_status()
        values = response.json()['summary']
        print(f"Observed={values['observed_events']}; SLI={values['sli']}; "
              f"remaining budget={values['remaining_budget']}; burn rate={values['burn_rate']}; "
              f"coverage={values['sample_coverage']}")


if __name__ == '__main__':
    main()
