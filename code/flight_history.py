"""Bounded, local-only completed flight archive. No video, audio, or credentials."""
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from contextlib import contextmanager


class FlightHistory:
    def __init__(self, path, limit=50):
        self.path = Path(path)
        self.limit = limit
        self._lock = threading.Lock()

    @contextmanager
    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        try:
            with connection:
                connection.execute("CREATE TABLE IF NOT EXISTS flights (sequence INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL)")
                yield connection
        finally:
            connection.close()

    def save(self, state):
        keys = ("flight_id", "score", "airtime", "smoothness", "path_length",
                "horizontal_distance", "speed", "angle", "frame_width", "frame_height",
                "trajectory", "trajectory_times")
        record = {key: state[key] for key in keys if key in state}
        record.update(history_id=uuid4().hex, completed_at=datetime.now(timezone.utc).isoformat())
        with self._lock, self._connect() as connection:
            connection.execute("INSERT INTO flights(payload) VALUES (?)", (json.dumps(record),))
            connection.execute("DELETE FROM flights WHERE sequence NOT IN (SELECT sequence FROM flights ORDER BY sequence DESC LIMIT ?)", (self.limit,))
        return record["history_id"]

    def list(self):
        with self._lock, self._connect() as connection:
            rows = connection.execute("SELECT payload FROM flights ORDER BY sequence DESC").fetchall()
        return [json.loads(row[0]) for row in rows]
