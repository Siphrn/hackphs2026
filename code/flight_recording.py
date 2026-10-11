"""Bounded local capture and background H.264 encoding; no camera ownership."""
import math
import tempfile
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np


class FlightRecorder:
    FPS = 20
    MAX_FLIGHT_SECONDS = 15
    PRE_ROLL_SECONDS = 1
    POST_ROLL_SECONDS = 1
    MAX_BUFFER_BYTES = 8 * 1024 * 1024
    MAX_CLIP_BYTES = 10 * 1024 * 1024

    def __init__(self, publish):
        self.publish = publish
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="flight-video")
        self._encoding = threading.BoundedSemaphore(1)
        self._pre_frames = deque()
        self._pre_bytes = 0
        self._last_observed = None
        self.reset()

    def reset(self):
        self.frames = []
        self.buffer_bytes = 0
        self.truncated = False
        self._clip_origin = None
        self._pending = None

    def cancel(self):
        """Cancel an unfinished flight, or preserve a completed clip immediately."""
        if self._pending:
            self._finish_active()
        else:
            self.reset()

    def _frame_payload(self, frame):
        height, width = frame.shape[:2]
        size = (min(640, width) // 2 * 2, max(2, round(height * min(640, width) / width) // 2 * 2))
        small = cv2.resize(frame, size)
        ok, encoded = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 70])
        return encoded.tobytes() if ok else None

    def observe(self, frame, timestamp):
        """Keep a rolling pre-roll and capture an active flight through post-roll."""
        if not math.isfinite(timestamp):
            return
        if self._last_observed is not None and timestamp - self._last_observed < 1 / self.FPS:
            return
        payload = self._frame_payload(frame)
        if payload is None:
            return
        self._last_observed = timestamp

        self._pre_frames.append((timestamp, payload))
        self._pre_bytes += len(payload)
        cutoff = timestamp - self.PRE_ROLL_SECONDS
        while self._pre_frames and (self._pre_frames[0][0] < cutoff or self._pre_bytes > self.MAX_BUFFER_BYTES):
            _, expired = self._pre_frames.popleft()
            self._pre_bytes -= len(expired)

        if self._clip_origin is not None:
            self._append(timestamp - self._clip_origin, payload)
            if self._pending and timestamp >= self._pending[3]:
                self._finish_active()

    def start(self, timestamp):
        """Start a flight clip with up to one second already buffered."""
        if self._clip_origin is not None:
            self._finish_active() if self._pending else self.reset()
        available = [(t, data) for t, data in self._pre_frames if t >= timestamp - self.PRE_ROLL_SECONDS]
        self._clip_origin = available[0][0] if available else timestamp
        for captured_at, payload in available:
            self._append(captured_at - self._clip_origin, payload)

    def complete(self, history_id, score, duration, flight_ended_at):
        """Finish after one second of camera footage beyond the last detection."""
        if self._clip_origin is None:
            return
        deadline = flight_ended_at + self.POST_ROLL_SECONDS
        self._pending = (history_id, score, duration, deadline)
        if self._last_observed is not None and self._last_observed >= deadline:
            self._finish_active()

    def _append(self, elapsed, payload):
        max_clip_seconds = self.PRE_ROLL_SECONDS + self.MAX_FLIGHT_SECONDS + self.POST_ROLL_SECONDS
        if self.truncated or elapsed < 0:
            return
        if elapsed > max_clip_seconds or self.buffer_bytes + len(payload) > self.MAX_BUFFER_BYTES:
            self.truncated = True
            return
        self.frames.append((elapsed, payload))
        self.buffer_bytes += len(payload)

    def capture(self, frame, elapsed):
        """Capture a directly-timed frame (kept for isolated encoder use/tests)."""
        if self.truncated:
            return
        if not math.isfinite(elapsed) or elapsed < 0:
            return
        if elapsed > self.MAX_FLIGHT_SECONDS:
            self.truncated = True
            return
        if self.frames and elapsed - self.frames[-1][0] < 1 / self.FPS:
            return
        payload = self._frame_payload(frame)
        if payload is None:
            return
        if self.buffer_bytes + len(payload) > self.MAX_BUFFER_BYTES:
            self.truncated = True
            return
        self.frames.append((elapsed, payload))
        self.buffer_bytes += len(payload)

    def finish(self, history_id, score, duration):
        frames, truncated = self.frames, self.truncated
        self.reset()
        self._submit(history_id, frames, score, duration, truncated)

    def _finish_active(self):
        history_id, score, duration, _ = self._pending or (None, 0, 0, 0)
        frames, truncated = self.frames, self.truncated
        self.reset()
        self._submit(history_id, frames, score, duration, truncated)

    def _submit(self, history_id, frames, score, duration, truncated):
        if not history_id:
            return
        if not frames or not self._encoding.acquire(blocking=False):
            self.publish(history_id, None, 0, False)
            return
        try:
            self._worker.submit(self._encode_and_publish, history_id, frames, score, duration, truncated)
        except RuntimeError:
            self._encoding.release()
            self.publish(history_id, None, 0, False)

    def _encode_and_publish(self, history_id, frames, score, duration, truncated):
        try:
            payload, clip_duration = self.encode(frames, score, duration)
            self.publish(history_id, payload, clip_duration, truncated or duration > self.MAX_FLIGHT_SECONDS)
        except Exception:
            # Recording is optional: never stop tracking, serial scores or history.
            self.publish(history_id, None, 0, False)
        finally:
            self._encoding.release()

    @classmethod
    def encode(cls, frames, score, duration):
        if not frames:
            raise ValueError("No flight video frames")
        first = cv2.imdecode(np.frombuffer(frames[0][1], np.uint8), cv2.IMREAD_COLOR)
        if first is None:
            raise ValueError("Invalid video frame")
        height, width = first.shape[:2]
        max_clip_seconds = cls.PRE_ROLL_SECONDS + cls.MAX_FLIGHT_SECONDS + cls.POST_ROLL_SECONDS
        clip_duration = min(max_clip_seconds, frames[-1][0] + 1 / cls.FPS)
        count = max(1, math.ceil(clip_duration * cls.FPS))
        # OpenCV needs a seekable filename to finalize the MP4 container. This
        # scratch file is removed immediately; only capped MP4 bytes survive in RAM.
        with tempfile.TemporaryDirectory(prefix="skytrace-encode-") as directory:
            path = Path(directory) / "flight.mp4"
            writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"avc1"), cls.FPS, (width, height))
            if not writer.isOpened():
                writer.release()
                raise RuntimeError("H.264 encoder unavailable")
            try:
                index = 0
                decoded = first
                for number in range(count):
                    timestamp = number / cls.FPS
                    while index + 1 < len(frames) and frames[index + 1][0] <= timestamp:
                        index += 1
                        decoded = cv2.imdecode(np.frombuffer(frames[index][1], np.uint8), cv2.IMREAD_COLOR)
                    if decoded is None:
                        raise ValueError("Invalid video frame")
                    output = cv2.resize(decoded, (width, height)).copy()
                    cv2.rectangle(output, (0, height - 34), (width, height), (15, 25, 20), -1)
                    text = f"SkyTrace | Score {int(score)}/100 | Flight {duration:.2f}s | {timestamp:.2f}s"
                    cv2.putText(output, text, (8, height - 12), cv2.FONT_HERSHEY_SIMPLEX, .43, (130, 235, 170), 1, cv2.LINE_AA)
                    writer.write(output)
                    if path.stat().st_size > cls.MAX_CLIP_BYTES:
                        raise ValueError("Clip exceeds size cap")
            finally:
                writer.release()
            if path.stat().st_size > cls.MAX_CLIP_BYTES:
                raise ValueError("Clip exceeds size cap")
            return path.read_bytes(), count / cls.FPS

    def close(self):
        if self._clip_origin is not None:
            self._finish_active()
        self._pre_frames.clear()
        self._pre_bytes = 0
        self._last_observed = None
        self._worker.shutdown(wait=True)
