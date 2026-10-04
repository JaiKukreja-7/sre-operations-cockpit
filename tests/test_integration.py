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
        with worker_lock(db.with_suffix('.worker.lock')):
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
