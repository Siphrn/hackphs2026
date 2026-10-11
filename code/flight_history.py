"""Session-only completed flights. Restarting the tracker starts empty."""
import copy
import math
import threading
from collections import deque
from datetime import datetime, timezone
from uuid import uuid4


class FlightHistory:
    def __init__(self, limit=50):
        self._records = deque(maxlen=limit)
        self._lock = threading.Lock()

    def save(self, state):
        try:
            duration = float(state.get("airtime", 0))
        except (ValueError, TypeError):
            return None
        if not math.isfinite(duration) or duration < .50:
            return None
        keys = ("flight_id", "score", "airtime", "smoothness", "path_length",
                "horizontal_distance", "speed", "angle", "frame_width", "frame_height",
                "trajectory", "trajectory_times")
        record = copy.deepcopy({key: state[key] for key in keys if key in state})
        record.update(history_id=uuid4().hex, name=f"Flight {state.get('flight_id', 0)}",
                      completed_at=datetime.now(timezone.utc).isoformat())
        with self._lock:
            self._records.appendleft(record)
        return record["history_id"]

    def list(self):
        with self._lock:
            return copy.deepcopy(list(self._records))

    def rename(self, history_id, name):
        if not isinstance(name, str):
            raise ValueError("Enter a flight name.")
        name = name.strip()
        if not 1 <= len(name) <= 60 or any(ord(char) < 32 for char in name):
            raise ValueError("Use a name between 1 and 60 characters.")
        with self._lock:
            for record in self._records:
                if record["history_id"] == history_id:
                    record["name"] = name
                    return name
        raise KeyError(history_id)
