import signal
import subprocess
from types import SimpleNamespace
import pytest
from cockpit import launch


@pytest.mark.parametrize('platform', ['posix', 'nt'])
def test_platform_spawn_and_shutdown_signals(monkeypatch, platform):
    spawned = []
    sent = []
    waited = []
    class Child:
        def poll(self):
            return None
        def send_signal(self, value):
            sent.append(value)
        def wait(self, timeout=None):
            waited.append(timeout)
            return 0
    child = Child()
    def popen(args, **options):
        spawned.append((args, options))
        return child
    monkeypatch.setattr(launch, 'os', SimpleNamespace(name=platform))
    monkeypatch.setattr(launch, 'subprocess', SimpleNamespace(
        CREATE_NEW_PROCESS_GROUP=512, Popen=popen, TimeoutExpired=subprocess.TimeoutExpired))
    monkeypatch.setattr(launch.signal, 'CTRL_BREAK_EVENT', 999, raising=False)
    assert launch.spawn(['-m', 'cockpit.worker']) is child
    options = spawned[0][1]
    if platform == 'nt':
        assert options['creationflags'] == 512
        assert 'start_new_session' not in options
    else:
        assert options['start_new_session'] is True
        assert 'creationflags' not in options
    launch.stop_children([child])
    assert sent == [999 if platform == 'nt' else signal.SIGTERM]
    # Valid >10-second probes must get enough time to complete normally.
    assert waited[0] > 60


def test_shutdown_forces_and_reaps_unresponsive_child():
    actions = []
    class Child:
        def poll(self):
            return None
        def send_signal(self, value):
            actions.append('signal')
        def wait(self, timeout=None):
            actions.append('wait')
            if timeout is not None:
                raise subprocess.TimeoutExpired('wedged child', timeout)
            return 0
        def kill(self):
            actions.append('kill')
    launch.stop_children([Child()], grace_seconds=.01)
    assert actions == ['signal', 'wait', 'kill', 'wait']
