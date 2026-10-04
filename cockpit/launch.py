"""Portable supervisor for two HTTP services and a separate monitoring worker."""
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parent.parent
# Allow the maximum supported 60-second request timeout plus SQLite contention
# and cleanup. Ordinary shutdown returns as soon as children exit.
SHUTDOWN_GRACE_SECONDS = 75


def spawn(args):
    options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    return subprocess.Popen([sys.executable, *args], cwd=ROOT, **options)


def stop_children(children, grace_seconds=SHUTDOWN_GRACE_SECONDS):
    for child in reversed(children):
        if child.poll() is None:
            try:
                child.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM)
            except (ProcessLookupError, OSError):
                pass
    deadline = time.monotonic() + grace_seconds
    for child in reversed(children):
        try:
            child.wait(timeout=max(.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()


def wait_ready(child, port, stop):
    deadline = time.monotonic() + 15
    with httpx.Client(trust_env=False, timeout=.5) as client:
        while time.monotonic() < deadline and not stop.is_set():
            if child.poll() is not None:
                raise RuntimeError(f"Service on port {port} exited with {child.returncode}")
            try:
                response = client.get(f"http://127.0.0.1:{port}/health")
                if response.status_code == 200 and response.json() == {"status": "ok"}:
                    return
            except (httpx.HTTPError, ValueError):
                pass
            stop.wait(.1)
    raise RuntimeError(f"Service on port {port} did not become ready (or startup cancelled)")


def main():
    if sys.version_info[:2] != (3, 11):
        print("Use Python 3.11; see README installation instructions.", file=sys.stderr)
        return 1
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, lambda *_: stop.set())
    api_host = os.environ.get("COCKPIT_API_HOST", "127.0.0.1")
    if api_host not in ("127.0.0.1", "0.0.0.0"):
        print("COCKPIT_API_HOST must be 127.0.0.1 or 0.0.0.0", file=sys.stderr)
        return 1
    try:
        api_port = int(os.environ.get("PORT", "8000"))
        if not 1 <= api_port <= 65535 or api_port == 8001:
            raise ValueError
    except ValueError:
        print("PORT must be 1-65535 and different from demo port 8001", file=sys.stderr)
        return 1
    children = []
    try:
        # Refuse to attach to unrelated services that already occupy our ports.
        for port in (api_port, 8001):
            with socket.socket() as connection:
                connection.settimeout(.2)
                # Detect live listeners, not TIME_WAIT sockets left after shutdown.
                # Let Uvicorn perform the actual bind using its platform semantics.
                if connection.connect_ex(("127.0.0.1", port)) == 0:
                    raise RuntimeError(f"Port {port} is already in use")
        for app, host, port in (("cockpit.demo:app", "127.0.0.1", 8001), ("cockpit.api:app", api_host, api_port)):
            child = spawn(["-m", "uvicorn", app, "--host", host, "--port", str(port)])
            children.append(child)
            wait_ready(child, port, stop)
        children.append(spawn(["-m", "cockpit.worker"]))
        print(f"Demo :8001, API :{api_port}, worker started. Press Ctrl+C to stop.", flush=True)
        print(f"Dashboard: http://127.0.0.1:{api_port} | API documentation: /docs", flush=True)
        while not stop.wait(.2):
            for child in children:
                if child.poll() is not None:
                    raise RuntimeError(f"Child process {child.pid} exited with {child.returncode}")
        return 0
    except (OSError, RuntimeError) as exc:
        if stop.is_set():
            return 0
        print(f"Startup/runtime failure: {exc}", file=sys.stderr)
        return 1
    finally:
        stop_children(children)


if __name__ == "__main__":
    raise SystemExit(main())
