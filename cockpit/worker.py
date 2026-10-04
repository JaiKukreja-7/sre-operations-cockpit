"""Single-owner worker; run with python -m cockpit.worker."""
import argparse
import os
import signal
import threading
from contextlib import contextmanager
import httpx
from cockpit.db import Store
from cockpit.probe import probe


@contextmanager
def worker_lock(path):
    """OS releases this advisory lock even after a crash (POSIX and Windows)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+b")
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("Another worker owns this database") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        handle.close()


def tick(store, client, now=None):
    job = store.claim_next(now)
    if job is None:
        return False
    if job["result_id"] is not None and not job["missed"]:
        result = probe(job["config"], client)
        store.complete(job["result_id"], result)
    return True


def run(store, stop):
    with worker_lock(store.lock_path):
        store.initialize()
        store.recover_interrupted()
        with httpx.Client(trust_env=False, follow_redirects=False) as client:
            while not stop.is_set():
                if not tick(store, client):
                    stop.wait(.1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db")
    args = parser.parse_args()
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, lambda *_: stop.set())
    try:
        run(Store(args.db), stop)
    except RuntimeError as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
