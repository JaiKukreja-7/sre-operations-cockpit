import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
import httpx
import pytest
from cockpit.db import Store
from cockpit.models import CheckConfig
from cockpit.worker import run, tick, worker_lock


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path / 'test.db')
    store.initialize(now=100)
    return store


def test_missed_slots_do_not_probe_and_coverage(store):
    seen = []
    with httpx.Client(transport=httpx.MockTransport(lambda req: seen.append(req))) as client:
        assert tick(store, client, now=111)
        assert tick(store, client, now=111)
    assert not seen
    rows = store.recent(1)
    assert [row['scheduled_at'] for row in rows] == [105, 100]
    assert all(row['outcome'] == 'UNKNOWN' and row['latency_ms'] is None for row in rows)
    from cockpit.reliability import window
    values = window(store, 1, 100, 110, .95)
    assert values['unknown'] == 2
    assert values['observed_events'] == 0
    assert values['sample_coverage'] == 0


def test_good_completion_and_atomic_duplicate_prevention(store):
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: store.claim_next(100), range(2)))
    assert sum(job is not None for job in claims) == 1
    job = next(job for job in claims if job)
    good = dict(outcome='GOOD', http_status=200, latency_ms=1, failure_reason=None)
    store.complete(job['result_id'], good, now=100.1)
    # Retry cannot overwrite a committed outcome.
    store.complete(job['result_id'], dict(good, outcome='BAD'), now=101)
    assert store.recent(1)[0]['outcome'] == 'GOOD'
    with pytest.raises(sqlite3.IntegrityError), store.connect() as conn:
        conn.execute('INSERT INTO results(check_id,schedule_id,scheduled_at,outcome) VALUES (1,1,100,?)', ('BAD',))
    assert len(store.recent(1)) == 1


def test_interrupted_claim_becomes_unknown_and_is_not_retried(store):
    store.claim_next(100)
    store.recover_interrupted(now=101)
    assert store.recent(1)[0]['outcome'] == 'UNKNOWN'
    assert 'interrupted' in store.recent(1)[0]['failure_reason']
    assert store.claim_next(101) is None
    assert store.claim_next(105)['scheduled_at'] == 105


def test_probe_tick(store):
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, text='synthetic demo OK'))) as client:
        assert tick(store, client, now=100)
        assert not tick(store, client, now=101)
    assert store.recent(1)[0]['outcome'] == 'GOOD'
    assert store.recent(1)[0]['completed_at'] is not None


def test_noop_update_keeps_anchor_and_disabled_check_stops(store):
    store.update_check(1, CheckConfig(), now=102)
    assert store.claim_next(100)['scheduled_at'] == 100
    store.update_check(1, CheckConfig(enabled=False), now=104)
    assert store.claim_next(105) is None


def test_worker_lock_excludes_duplicate_and_releases(tmp_path):
    path = tmp_path / 'worker.lock'
    with worker_lock(path):
        with pytest.raises(RuntimeError, match='Another worker'):
            with worker_lock(path):
                pass
    with worker_lock(path):
        pass


def test_worker_idle_stop_and_restart(tmp_path):
    store = Store(tmp_path / 'test.db')
    # Disabled schedule ensures this lifecycle test makes no real network requests.
    store.initialize(now=100)
    store.update_check(1, CheckConfig(enabled=False), now=100)
    for _ in range(2):
        stop = threading.Event()
        failures = []
        def target():
            try:
                run(store, stop)
            except BaseException as exc:
                failures.append(exc)
        thread = threading.Thread(target=target)
        thread.start()
        stop.set()
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert not failures


def test_dispatch_time_is_evaluated_after_write_lock(store, monkeypatch):
    from contextlib import contextmanager
    entered = threading.Event()
    clock = {'now': 100}
    monkeypatch.setattr('cockpit.db.time.time', lambda: clock['now'])
    base_connect = store.connect

    @contextmanager
    def notify_connect():
        with base_connect() as conn:
            entered.set()
            yield conn

    monkeypatch.setattr(store, 'connect', notify_connect)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with base_connect() as writer:
            writer.execute('BEGIN IMMEDIATE')
            future = pool.submit(store.claim_next)
            assert entered.wait(timeout=2)
            clock['now'] = 110  # The worker waited long enough to miss its slot.
        job = future.result(timeout=5)
    assert job['missed'] is True
    assert store.recent(1)[0]['outcome'] == 'UNKNOWN'
