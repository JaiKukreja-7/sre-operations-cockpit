import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from cockpit.models import CheckConfig, DEFAULT_POLICIES, DISPATCH_GRACE_SECONDS

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "cockpit.db"


class Store:
    def __init__(self, path=None):
        self.path = Path(path or os.environ.get("COCKPIT_DB", DEFAULT_DB)).resolve()

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self, now=None):
        now = time.time() if now is None else now
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS checks (
                    id INTEGER PRIMARY KEY, config TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS schedules (
                    id INTEGER PRIMARY KEY, check_id INTEGER NOT NULL REFERENCES checks(id),
                    config TEXT NOT NULL, start REAL NOT NULL, end REAL,
                    next_slot REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS results (
                    id INTEGER PRIMARY KEY, check_id INTEGER NOT NULL REFERENCES checks(id),
                    schedule_id INTEGER NOT NULL REFERENCES schedules(id),
                    scheduled_at REAL NOT NULL, completed_at REAL,
                    http_status INTEGER, latency_ms REAL,
                    outcome TEXT NOT NULL CHECK(outcome IN ('PENDING','GOOD','BAD','UNKNOWN')),
                    failure_reason TEXT,
                    UNIQUE(check_id, scheduled_at)
                );
                CREATE INDEX IF NOT EXISTS results_window ON results(check_id, scheduled_at);
                CREATE TABLE IF NOT EXISTS policies (name TEXT PRIMARY KEY, config TEXT NOT NULL);
            """)
            conn.execute("BEGIN IMMEDIATE")
            if not conn.execute("SELECT 1 FROM checks LIMIT 1").fetchone():
                self._insert_check(conn, CheckConfig(), now)
            for name, policy in DEFAULT_POLICIES.items():
                conn.execute("INSERT OR IGNORE INTO policies VALUES (?, ?)",
                             (name, policy.model_dump_json()))

    @staticmethod
    def _insert_check(conn, config, now):
        encoded = config.model_dump_json()
        check_id = conn.execute("INSERT INTO checks(config) VALUES (?)", (encoded,)).lastrowid
        if config.enabled:
            conn.execute("INSERT INTO schedules(check_id,config,start,next_slot) VALUES (?,?,?,?)",
                         (check_id, encoded, now, now))
        return check_id

    def create_check(self, config, now=None):
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            return self._insert_check(conn, config, time.time() if now is None else now)

    def checks(self):
        with self.connect() as conn:
            return [dict(id=row["id"], **json.loads(row["config"]))
                    for row in conn.execute("SELECT * FROM checks ORDER BY id")]

    def update_check(self, check_id, config, now=None):
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            now = time.time() if now is None else now
            existing = conn.execute("SELECT config FROM checks WHERE id=?", (check_id,)).fetchone()
            if not existing:
                raise KeyError(check_id)
            # A no-op update preserves the schedule and its original eligibility.
            encoded = config.model_dump_json()
            if existing["config"] == encoded:
                return
            conn.execute("UPDATE schedules SET end=? WHERE check_id=? AND end IS NULL", (now, check_id))
            conn.execute("UPDATE checks SET config=? WHERE id=?", (encoded, check_id))
            if config.enabled:
                conn.execute("INSERT INTO schedules(check_id,config,start,next_slot) VALUES (?,?,?,?)",
                             (check_id, encoded, now, now))

    def claim_next(self, now=None):
        """Advance a durable schedule and claim its slot in one transaction.

        A worker may start a probe within one second of its scheduled time. Older
        slots are UNKNOWN; they are never replaced with present-time probes.
        """
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            # Lock contention must not make a stale dispatch timestamp look fresh.
            now = time.time() if now is None else now
            row = conn.execute("""SELECT * FROM schedules WHERE next_slot <= ?
                AND (end IS NULL OR next_slot < end) ORDER BY next_slot, id LIMIT 1""", (now,)).fetchone()
            if row is None:
                return None
            config = CheckConfig.model_validate_json(row["config"])
            slot = row["next_slot"]
            conn.execute("UPDATE schedules SET next_slot=? WHERE id=?",
                         (slot + config.interval_seconds, row["id"]))
            missed = now - slot > DISPATCH_GRACE_SECONDS
            cursor = conn.execute("""INSERT OR IGNORE INTO results
                (check_id,schedule_id,scheduled_at,completed_at,outcome,failure_reason)
                VALUES (?,?,?,?,?,?)""", (row["check_id"], row["id"], slot,
                                         now if missed else None,
                                         "UNKNOWN" if missed else "PENDING",
                                         "scheduled slot missed" if missed else None))
            return {"result_id": cursor.lastrowid if cursor.rowcount else None,
                    "config": config, "missed": missed, "scheduled_at": slot}

    def complete(self, result_id, result, now=None):
        with self.connect() as conn:
            conn.execute("""UPDATE results SET completed_at=?,http_status=?,latency_ms=?,
                outcome=?,failure_reason=? WHERE id=? AND outcome='PENDING'""",
                         (time.time() if now is None else now, result["http_status"],
                          result["latency_ms"], result["outcome"], result["failure_reason"], result_id))

    def recover_interrupted(self, now=None):
        with self.connect() as conn:
            conn.execute("""UPDATE results SET outcome='UNKNOWN',completed_at=?,
                failure_reason='worker interrupted before result was committed'
                WHERE outcome='PENDING'""", (time.time() if now is None else now,))

    def recent(self, check_id, limit=100):
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT * FROM results WHERE check_id=? AND outcome != 'PENDING' ORDER BY scheduled_at DESC LIMIT ?", (check_id, limit))]

    def policy(self, name):
        with self.connect() as conn:
            row = conn.execute("SELECT config FROM policies WHERE name=?", (name,)).fetchone()
            if row is None:
                raise KeyError(name)
            return json.loads(row["config"])

    def set_policy(self, name, policy):
        with self.connect() as conn:
            conn.execute("UPDATE policies SET config=? WHERE name=?", (policy.model_dump_json(), name))
