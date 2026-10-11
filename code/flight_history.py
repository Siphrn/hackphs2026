"""Persistent local plane profiles, completed flights, and bounded video clips."""
import copy
import json
import math
import os
import threading
from collections import OrderedDict, deque
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


class FlightHistory:
    def __init__(self, limit=50, video_limit_bytes=100 * 1024 * 1024, storage_directory=None):
        self._records = deque(maxlen=limit)
        self._lock = threading.Lock()
        self._profiles = []
        self._active_profile_id = None
        self._videos = OrderedDict()
        self._video_limit = video_limit_bytes
        self._video_bytes = 0
        self._storage_directory = Path(storage_directory) if storage_directory else None
        self._metadata_path = self._storage_directory / "history.json" if self._storage_directory else None
        self._video_directory = self._storage_directory / "videos" if self._storage_directory else None
        if self._storage_directory:
            self._load()

    @staticmethod
    def _valid_identifier(value):
        return isinstance(value, str) and len(value) == 32 and all(character in "0123456789abcdef" for character in value)

    def _load(self):
        try:
            document = json.loads(self._metadata_path.read_text(encoding="utf-8"))
            profiles = document.get("profiles", [])
            records = document.get("flights", [])
            if not isinstance(profiles, list) or not isinstance(records, list):
                raise ValueError("Invalid SkyTrace history format")
        except FileNotFoundError:
            return
        except (OSError, ValueError, json.JSONDecodeError) as error:
            print(f"Could not load saved SkyTrace history: {error}")
            return

        clean_profiles = []
        for profile in profiles[:30]:
            if (isinstance(profile, dict) and self._valid_identifier(profile.get("id"))
                    and isinstance(profile.get("name"), str) and 1 <= len(profile["name"]) <= 60):
                clean_profiles.append({"id": profile["id"], "name": profile["name"]})
        profile_ids = {profile["id"] for profile in clean_profiles}
        active = document.get("active_profile_id")
        self._profiles = clean_profiles
        self._active_profile_id = active if active in profile_ids else None

        clean_records = []
        for record in records[:self._records.maxlen]:
            if not isinstance(record, dict) or not self._valid_identifier(record.get("history_id")):
                continue
            restored = copy.deepcopy(record)
            if restored.get("profile_id") not in profile_ids:
                restored["profile_id"] = None
            if restored.get("video_status") == "pending":
                restored["video_status"] = "unavailable"
            clean_records.append(restored)
        self._records.extend(clean_records)

        # Rebuild oldest-to-newest so storage-cap eviction remains chronological.
        for record in reversed(self._records):
            if record.get("video_status") != "ready":
                continue
            path = self._video_path(record["history_id"])
            try:
                payload = path.read_bytes()
            except OSError:
                record["video_status"] = "unavailable"
                continue
            if not payload or self._video_bytes + len(payload) > self._video_limit:
                record["video_status"] = "expired"
                continue
            self._videos[record["history_id"]] = payload
            self._video_bytes += len(payload)

    def _video_path(self, history_id):
        return self._video_directory / f"{history_id}.mp4"

    def _persist_locked(self):
        if not self._storage_directory:
            return
        self._storage_directory.mkdir(parents=True, exist_ok=True)
        document = {
            "version": 1,
            "profiles": self._profiles,
            "active_profile_id": self._active_profile_id,
            "flights": list(self._records),
        }
        temporary = self._metadata_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(document, separators=(",", ":"), allow_nan=False), encoding="utf-8")
        os.replace(temporary, self._metadata_path)

    def _write_video_locked(self, history_id, payload):
        if not self._video_directory:
            return
        self._video_directory.mkdir(parents=True, exist_ok=True)
        destination = self._video_path(history_id)
        temporary = destination.with_suffix(".mp4.tmp")
        temporary.write_bytes(payload)
        os.replace(temporary, destination)

    def _remove_video_locked(self, history_id):
        previous = self._videos.pop(history_id, b"")
        self._video_bytes -= len(previous)
        if self._video_directory:
            try:
                self._video_path(history_id).unlink()
            except FileNotFoundError:
                pass

    def attach_video(self, history_id, payload, duration=0, truncated=False):
        with self._lock:
            record = next((record for record in self._records if record["history_id"] == history_id), None)
            if record is None:
                return
            self._remove_video_locked(history_id)
            record["video_status"] = "unavailable"
            if not payload or len(payload) > self._video_limit:
                self._persist_locked()
                return
            while self._video_bytes + len(payload) > self._video_limit and self._videos:
                expired = next(iter(self._videos))
                self._remove_video_locked(expired)
                for old in self._records:
                    if old["history_id"] == expired:
                        old["video_status"] = "expired"
                        break
            self._write_video_locked(history_id, payload)
            self._videos[history_id] = payload
            self._video_bytes += len(payload)
            record.update(video_status="ready", video_duration=duration, video_truncated=bool(truncated))
            self._persist_locked()

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
                if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60 or any(ord(character) < 32 for character in name):
                    raise ValueError("Use a plane name between 1 and 60 characters.")
                if len(self._profiles) >= 30:
                    raise ValueError("You can create up to 30 planes.")
                profile = {"id": uuid4().hex, "name": name.strip()}
                self._profiles.append(profile)
                self._active_profile_id = profile["id"]
            elif action == "reorder":
                order = values.get("order")
                if (not isinstance(order, list) or any(not isinstance(identifier, str) for identifier in order)
                        or len(order) != len(self._profiles) or set(order) != {profile["id"] for profile in self._profiles}):
                    raise ValueError("Plane list changed. Please try again.")
                lookup = {profile["id"]: profile for profile in self._profiles}
                self._profiles = [lookup[identifier] for identifier in order]
            elif action in ("select", "assign"):
                identifier = values.get("profile_id")
                if identifier is not None and not any(profile["id"] == identifier for profile in self._profiles):
                    raise ValueError("Plane not found.")
                if action == "select":
                    self._active_profile_id = identifier
                else:
                    record = next((record for record in self._records if record["history_id"] == values.get("history_id")), None)
                    if record is None:
                        raise KeyError(values.get("history_id"))
                    record["profile_id"] = identifier
            elif action == "delete":
                identifier = values.get("profile_id")
                if not any(profile["id"] == identifier for profile in self._profiles):
                    raise KeyError(identifier)
                self._profiles = [profile for profile in self._profiles if profile["id"] != identifier]
                if self._active_profile_id == identifier:
                    self._active_profile_id = None
                deleted_flights = [record["history_id"] for record in self._records if record.get("profile_id") == identifier]
                for history_id in deleted_flights:
                    self._remove_video_locked(history_id)
                self._records = deque(
                    (record for record in self._records if record.get("profile_id") != identifier),
                    maxlen=self._records.maxlen,
                )
            else:
                raise ValueError("Unknown profile action.")
            self._persist_locked()

    def save(self, state):
        try:
            duration = float(state.get("airtime", 0))
        except (ValueError, TypeError):
            return None
        if not math.isfinite(duration) or duration < 0:
            return None
        keys = ("flight_id", "score", "airtime", "smoothness", "path_length",
                "horizontal_distance", "speed", "angle", "frame_width", "frame_height",
                "trajectory", "trajectory_times", "profile_id", "video_status")
        record = copy.deepcopy({key: state[key] for key in keys if key in state})
        record.update(history_id=uuid4().hex, name=f"Flight {state.get('flight_id', 0)}",
                      completed_at=datetime.now(timezone.utc).isoformat())
        with self._lock:
            if len(self._records) == self._records.maxlen:
                self._remove_video_locked(self._records[-1]["history_id"])
            self._records.appendleft(record)
            self._persist_locked()
        return record["history_id"]

    def list(self):
        with self._lock:
            return copy.deepcopy(list(self._records))

    def rename(self, history_id, name):
        if not isinstance(name, str):
            raise ValueError("Enter a flight name.")
        name = name.strip()
        if not 1 <= len(name) <= 60 or any(ord(character) < 32 for character in name):
            raise ValueError("Use a name between 1 and 60 characters.")
        with self._lock:
            for record in self._records:
                if record["history_id"] == history_id:
                    record["name"] = name
                    self._persist_locked()
                    return name
        raise KeyError(history_id)

    def delete(self, history_id):
        with self._lock:
            if not any(record["history_id"] == history_id for record in self._records):
                raise KeyError(history_id)
            self._records = deque(
                (record for record in self._records if record["history_id"] != history_id),
                maxlen=self._records.maxlen,
            )
            self._remove_video_locked(history_id)
            self._persist_locked()
