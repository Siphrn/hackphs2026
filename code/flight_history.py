"""Session-only completed flights. Restarting the tracker starts empty."""
import copy
import math
import threading
from collections import deque, OrderedDict
from datetime import datetime, timezone
from uuid import uuid4


class FlightHistory:
    def __init__(self, limit=50, video_limit_bytes=100 * 1024 * 1024):
        self._records = deque(maxlen=limit)
        self._lock = threading.Lock()
        self._profiles = []
        self._active_profile_id = None
        self._videos = OrderedDict()
        self._video_limit = video_limit_bytes
        self._video_bytes = 0

    def attach_video(self, history_id, payload, duration=0, truncated=False):
        with self._lock:
            record = next((r for r in self._records if r["history_id"] == history_id), None)
            if record is None:
                return
            previous = self._videos.pop(history_id, b"")
            self._video_bytes -= len(previous)
            record["video_status"] = "unavailable"
            if not payload or len(payload) > self._video_limit:
                return
            while self._video_bytes + len(payload) > self._video_limit:
                expired, data = self._videos.popitem(last=False)
                self._video_bytes -= len(data)
                for old in self._records:
                    if old["history_id"] == expired:
                        old["video_status"] = "expired"
            self._videos[history_id] = payload
            self._video_bytes += len(payload)
            record.update(video_status="ready", video_duration=duration, video_truncated=bool(truncated))

    def video(self, history_id):
        with self._lock:
            return self._videos.get(history_id)

    def profiles(self):
        with self._lock:
            return copy.deepcopy({"profiles": self._profiles, "active_profile_id": self._active_profile_id})

    def change_profile(self, action, **values):
        with self._lock:
            if action == "create":
                name = values.get("name")
                if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60 or any(ord(c) < 32 for c in name):
                    raise ValueError("Use a plane name between 1 and 60 characters.")
                if len(self._profiles) >= 30:
                    raise ValueError("You can create up to 30 planes per session.")
                profile = {"id": uuid4().hex, "name": name.strip()}
                self._profiles.append(profile)
                self._active_profile_id = profile["id"]
            elif action == "reorder":
                order = values.get("order")
                if (not isinstance(order, list) or any(not isinstance(i, str) for i in order)
                        or len(order) != len(self._profiles) or set(order) != {p["id"] for p in self._profiles}):
                    raise ValueError("Plane list changed. Please try again.")
                lookup = {p["id"]: p for p in self._profiles}
                self._profiles = [lookup[i] for i in order]
            elif action in ("select", "assign"):
                identifier = values.get("profile_id")
                if identifier is not None and not any(p["id"] == identifier for p in self._profiles):
                    raise ValueError("Plane not found.")
                if action == "select":
                    self._active_profile_id = identifier
                else:
                    record = next((r for r in self._records if r["history_id"] == values.get("history_id")), None)
                    if record is None:
                        raise KeyError(values.get("history_id"))
                    record["profile_id"] = identifier
            else:
                raise ValueError("Unknown profile action.")

    def save(self, state):
        try:
            duration = float(state.get("airtime", 0))
        except (ValueError, TypeError):
            return None
        if not math.isfinite(duration) or duration < .50:
            return None
        keys = ("flight_id", "score", "airtime", "smoothness", "path_length",
                "horizontal_distance", "speed", "angle", "frame_width", "frame_height",
                "trajectory", "trajectory_times", "profile_id", "video_status")
        record = copy.deepcopy({key: state[key] for key in keys if key in state})
        record.update(history_id=uuid4().hex, name=f"Flight {state.get('flight_id', 0)}",
                      completed_at=datetime.now(timezone.utc).isoformat())
        with self._lock:
            if len(self._records) == self._records.maxlen:
                self._video_bytes -= len(self._videos.pop(self._records[-1]["history_id"], b""))
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
