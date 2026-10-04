"""Concurrent connections and transactions against a real SQLite WAL database."""
import threading
from concurrent.futures import ThreadPoolExecutor
from cockpit.db import Store
from cockpit.models import CheckConfig
from cockpit.reliability import summary


def test_concurrent_initialization_seeds_once(tmp_path):
    path = tmp_path / 'fresh.db'
    barrier = threading.Barrier(8)
    def initialize(_):
        barrier.wait(timeout=5)
        Store(path).initialize(now=100)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(initialize, range(8)))
    store = Store(path)
    assert len(store.checks()) == 1
    with store.connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM schedules').fetchone()[0] == 1
        assert conn.execute('SELECT COUNT(*) FROM policies').fetchone()[0] == 2
        assert conn.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
        assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'


def test_parallel_configuration_claims_and_summaries(tmp_path):
    path = tmp_path / 'concurrent.db'
    store = Store(path)
    store.initialize(now=100)
    store.update_check(1, CheckConfig(enabled=False), now=100)
    barrier = threading.Barrier(8)
    def work(index):
        local = Store(path)
        barrier.wait(timeout=5)
        check_id = local.create_check(CheckConfig(name=f'check {index}'), now=200)
        for slot in range(200, 230, 5):
            job = local.claim_next(slot)
            if job and not job['missed']:
                local.complete(job['result_id'], dict(outcome='GOOD', http_status=200,
                               latency_ms=1, failure_reason=None), now=slot + .1)
            local.update_check(check_id, CheckConfig(name=f'check {index}'), now=slot)
            values = summary(local, check_id, 'demo', slot + .5)['summary']
            assert values['observed_events'] <= values['eligible_slots']
            assert values['unknown'] + values['pending'] + values['observed_events'] <= values['eligible_slots']
        return check_id
    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(work, range(8)))
    assert len(set(ids)) == 8
    with store.connect() as conn:
        assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert conn.execute('SELECT COUNT(*) FROM results').fetchone()[0] == conn.execute(
            'SELECT COUNT(*) FROM (SELECT check_id,scheduled_at FROM results GROUP BY check_id,scheduled_at)').fetchone()[0]
