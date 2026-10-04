"""Real HTTP requests, independent OS processes, and durable SQLite scheduling."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import httpx
from cockpit.demonstrate import demonstrate
from cockpit.worker import worker_lock

ROOT = Path(__file__).resolve().parent.parent


def start(log, env):
    options = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
    return subprocess.Popen([sys.executable, '-m', 'cockpit.launch'], cwd=ROOT,
                            env=env, stdout=log, stderr=subprocess.STDOUT, **options)


def ready(process, client):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        assert process.poll() is None, 'Launcher failed; inspect captured launcher log'
        try:
            response = client.get('/api/checks/1/results')
            if response.status_code == 200 and any(row['outcome'] == 'GOOD' for row in response.json()):
                return
        except httpx.HTTPError:
            pass
        time.sleep(.1)
    raise AssertionError('No GOOD result from real worker')


def shutdown(process):
    if process.poll() is None:
        process.send_signal(signal.CTRL_BREAK_EVENT if os.name == 'nt' else signal.SIGINT)
    try:
        assert process.wait(timeout=15) == 0
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        raise


def test_real_demo_sequence_duplicate_worker_shutdown_and_restart(tmp_path):
    db = tmp_path / 'integration.db'
    env = dict(os.environ, COCKPIT_DB=str(db))
    log_path = tmp_path / 'launcher.log'
    with log_path.open('w') as log, httpx.Client(base_url='http://127.0.0.1:8000', trust_env=False, timeout=3) as client:
        process = start(log, env)
        try:
            ready(process, client)
            assert client.get('/docs').status_code == 200
            assert client.get('/api/demo').json()['mode'] == 'Healthy'
            duplicate_launcher = subprocess.run([sys.executable, '-m', 'cockpit.launch'], cwd=ROOT,
                                                env=env, capture_output=True, text=True, timeout=5)
            assert duplicate_launcher.returncode == 1
            assert 'already in use' in duplicate_launcher.stderr
            assert process.poll() is None
            duplicate = subprocess.run([sys.executable, '-m', 'cockpit.worker'], cwd=ROOT,
                                       env=env, capture_output=True, text=True, timeout=5)
            assert duplicate.returncode == 1
            assert 'Another worker' in duplicate.stderr
            rows = demonstrate(client)
            assert [row['outcome'] for row in rows] == ['GOOD', 'BAD', 'BAD', 'GOOD']
            assert len({row['scheduled_at'] for row in rows}) == 4
            values = client.get('/api/checks/1/summary').json()['summary']
            assert values['bad'] == 2
            assert values['remaining_budget'] < 0
            assert values['sample_coverage'] > 0
            previous_ids = {row['id'] for row in client.get('/api/checks/1/results').json()}
        finally:
            shutdown(process)
        # Both HTTP children are stopped and worker ownership is released.
        for port in (8000, 8001):
            try:
                httpx.get(f'http://127.0.0.1:{port}/health', trust_env=False, timeout=.5)
            except httpx.ConnectError:
                pass
            else:
                raise AssertionError(f'Child service on {port} still running')
        with worker_lock(db.with_name(db.name + '.worker.lock')):
            pass
        process = start(log, env)
        try:
            ready(process, client)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                restarted = client.get('/api/checks/1/results').json()
                if any(row['id'] not in previous_ids and row['outcome'] == 'GOOD' for row in restarted):
                    break
                time.sleep(.1)
            else:
                raise AssertionError('Restarted worker produced no new GOOD result')
            assert previous_ids.issubset({row['id'] for row in restarted})
        finally:
            shutdown(process)
    print(log_path.read_text())


def test_shell_wrapper_startup_and_shutdown(tmp_path):
    if os.name == 'nt':
        import pytest
        pytest.skip('POSIX shell wrapper; Windows launcher is tested through Python')
    env = dict(os.environ, COCKPIT_DB=str(tmp_path / 'wrapper.db'))
    with (tmp_path / 'wrapper.log').open('w') as log, httpx.Client(
            base_url='http://127.0.0.1:8000', trust_env=False, timeout=3) as client:
        process = subprocess.Popen(['bash', str(ROOT / 'start_mac.sh')], cwd=tmp_path,
                                   env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            ready(process, client)
        finally:
            shutdown(process)
        for port in (8000, 8001):
            try:
                httpx.get(f'http://127.0.0.1:{port}/health', trust_env=False, timeout=.5)
            except httpx.ConnectError:
                pass
            else:
                raise AssertionError(f'Shell wrapper left service on {port} running')


def test_killed_worker_recovers_pending_slot_without_replaying(tmp_path):
    from cockpit.db import Store
    db = tmp_path / 'crash.db'
    store = Store(db)
    options = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
    env = dict(os.environ, COCKPIT_DB=str(db))
    with (tmp_path / 'crash.log').open('w') as log, httpx.Client(
            base_url='http://127.0.0.1:8001', trust_env=False, timeout=3) as client:
        demo = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'cockpit.demo:app',
                                 '--host', '127.0.0.1', '--port', '8001'], cwd=ROOT,
                                env=env, stdout=log, stderr=subprocess.STDOUT, **options)
        worker = None
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                assert demo.poll() is None
                try:
                    if client.get('/health').status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(.05)
            else:
                raise AssertionError('Demo failed to start')
            assert client.put('/mode', json={'mode': 'Slow', 'delay_seconds': 1.5}).status_code == 200
            store.initialize()
            worker = subprocess.Popen([sys.executable, '-m', 'cockpit.worker'], cwd=ROOT,
                                      env=env, stdout=log, stderr=subprocess.STDOUT, **options)
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                assert worker.poll() is None
                with store.connect() as conn:
                    pending = conn.execute("SELECT * FROM results WHERE outcome='PENDING'").fetchone()
                if pending:
                    break
                time.sleep(.02)
            else:
                raise AssertionError('Worker never claimed a request')
            # Terminate the actual process during its request; no cleanup runs.
            worker.kill()
            worker.wait(timeout=5)
            assert client.put('/mode', json={'mode': 'Healthy'}).status_code == 200
            worker = subprocess.Popen([sys.executable, '-m', 'cockpit.worker'], cwd=ROOT,
                                      env=env, stdout=log, stderr=subprocess.STDOUT, **options)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                assert worker.poll() is None
                rows = store.recent(1)
                if any(row['outcome'] == 'GOOD' and row['scheduled_at'] > pending['scheduled_at'] for row in rows):
                    break
                time.sleep(.05)
            else:
                raise AssertionError('Replacement worker produced no later GOOD result')
            interrupted = [row for row in rows if row['scheduled_at'] == pending['scheduled_at']]
            assert len(interrupted) == 1
            assert interrupted[0]['id'] == pending['id']
            assert interrupted[0]['outcome'] == 'UNKNOWN'
            assert 'interrupted' in interrupted[0]['failure_reason']
            assert interrupted[0]['http_status'] is None
            assert interrupted[0]['latency_ms'] is None
        finally:
            for child in (worker, demo):
                if child is not None and child.poll() is None:
                    child.send_signal(signal.CTRL_BREAK_EVENT if os.name == 'nt' else signal.SIGTERM)
                    try:
                        child.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait()
        with worker_lock(store.lock_path):
            pass


def test_shutdown_during_long_valid_probe_preserves_result(tmp_path):
    from cockpit.db import Store
    from cockpit.models import CheckConfig
    db = tmp_path / 'long-probe.db'
    store = Store(db)
    store.initialize()
    # The previous ten-second supervisor deadline killed this valid probe.
    store.update_check(1, CheckConfig(timeout_seconds=14, interval_seconds=15,
                                   latency_threshold_ms=12000), now=time.time())
    env = dict(os.environ, COCKPIT_DB=str(db))
    with (tmp_path / 'long.log').open('w') as log, httpx.Client(
            base_url='http://127.0.0.1:8000', trust_env=False, timeout=3) as client:
        process = start(log, env)
        try:
            ready(process, client)
            assert client.put('/api/demo', json={'mode': 'Slow', 'delay_seconds': 11}).status_code == 200
            # Reconfigure to make a fresh slot immediately eligible.
            config = CheckConfig(name='long shutdown probe', timeout_seconds=14,
                                 interval_seconds=15, latency_threshold_ms=12000)
            assert client.put('/api/checks/1', json=config.model_dump()).status_code == 200
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                with store.connect() as conn:
                    pending = conn.execute("SELECT * FROM results WHERE outcome='PENDING'").fetchone()
                if pending:
                    # Ensure the HTTP request actually reached the delayed endpoint.
                    time.sleep(.3)
                    break
                time.sleep(.02)
            else:
                raise AssertionError('No long probe claimed')
            shutdown(process)
            rows = store.recent(1)
            result = next(row for row in rows if row['id'] == pending['id'])
            assert result['outcome'] == 'GOOD'
            assert result['latency_ms'] >= 10000
            assert result['http_status'] == 200
        finally:
            if process.poll() is None:
                shutdown(process)
        with worker_lock(store.lock_path):
            pass
