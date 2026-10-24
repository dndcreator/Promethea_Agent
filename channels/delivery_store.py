"""Durable transport inbox/outbox, not Agent execution or Memory truth."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import time


class DeliveryStore:
    def __init__(self, path, *, queue_limit=200, retention_days=30):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.queue_limit = queue_limit
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS deliveries (
                    delivery_id TEXT PRIMARY KEY, channel TEXT NOT NULL,
                    user_id TEXT NOT NULL, session_id TEXT NOT NULL,
                    state TEXT NOT NULL, envelope TEXT NOT NULL,
                    response TEXT, next_part INTEGER NOT NULL DEFAULT 0,
                    error_code TEXT, execution_status TEXT, created REAL NOT NULL, updated REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS delivery_state ON deliveries(state, created);
            """)
            db.execute("DELETE FROM deliveries WHERE updated < ? AND state IN ('delivered','failed','delivery_failed','revoked')", (time.time() - retention_days * 86400,))

    def recover(self):
        with self.connect() as db:
            # Called only after acquiring the single-instance transport lock.
            db.execute("UPDATE deliveries SET state='uncertain', error_code='RUNTIME_INTERRUPTED', updated=? WHERE state IN ('processing','delivering')", (time.time(),))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA journal_mode=WAL")
            with db:
                yield db
        finally:
            db.close()

    def get(self, delivery_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM deliveries WHERE delivery_id=?", (delivery_id,)).fetchone()
            return dict(row) if row else None

    def enqueue(self, delivery_id, channel, user_id, session_id, envelope, *, response=None):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM deliveries WHERE delivery_id=?", (delivery_id,)).fetchone():
                return False
            pending = db.execute("SELECT count(*) FROM deliveries WHERE state IN ('queued','processing','ready','delivering')").fetchone()[0]
            if pending >= self.queue_limit:
                raise OverflowError("channel inbox is full")
            now = time.time()
            db.execute("INSERT INTO deliveries(delivery_id,channel,user_id,session_id,state,envelope,response,created,updated) VALUES(?,?,?,?,?,?,?,?,?)", (delivery_id, channel, user_id, session_id, "ready" if response is not None else "queued", json.dumps(envelope, ensure_ascii=False), json.dumps(response, ensure_ascii=False) if response is not None else None, now, now))
            return True

    def ensure_capacity(self):
        with self.connect() as db:
            if db.execute("SELECT count(*) FROM deliveries WHERE state IN ('queued','processing','ready','delivering')").fetchone()[0] >= self.queue_limit:
                raise OverflowError("channel inbox is full")

    def claim(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM deliveries WHERE state IN ('queued','ready') ORDER BY created, rowid LIMIT 1").fetchone()
            if not row:
                return None
            state = "processing" if row["state"] == "queued" else "delivering"
            db.execute("UPDATE deliveries SET state=?, updated=? WHERE delivery_id=?", (state, time.time(), row["delivery_id"]))
            return {**dict(row), "state": state}

    def update(self, identity, state, *, response=None, next_part=None, error_code=None):
        fields, values = ["state=?", "updated=?", "error_code=?"], [state, time.time(), error_code]
        if response is not None:
            fields.append("response=?")
            values.append(json.dumps(response, ensure_ascii=False))
            fields.append("execution_status=?")
            values.append(response.get("execution_status"))
        if next_part is not None:
            fields.append("next_part=?")
            values.append(next_part)
        with self.connect() as db:
            db.execute(f"UPDATE deliveries SET {', '.join(fields)} WHERE delivery_id=?", (*values, identity))

    def list_user(self, user_id):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT delivery_id,channel,session_id,state,execution_status,next_part,error_code,created,updated FROM deliveries WHERE user_id=? ORDER BY created DESC LIMIT 100", (user_id,))]

    def purge(self, user_id):
        with self.connect() as db:
            db.execute("DELETE FROM deliveries WHERE user_id=?", (user_id,))
