"""Bounded local capture and background H.264 encoding; no camera ownership."""
import math
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np


class FlightRecorder:
    FPS = 20
    MAX_SECONDS = 15
    MAX_BUFFER_BYTES = 8 * 1024 * 1024
    MAX_CLIP_BYTES = 10 * 1024 * 1024

    def __init__(self, publish):
        self.publish = publish
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="flight-video")
        self._encoding = threading.BoundedSemaphore(1)
        self.reset()

    def reset(self):
        self.frames = []
        self.buffer_bytes = 0
        self.truncated = False

    def capture(self, frame, elapsed):
        if self.truncated:
            return
        if not math.isfinite(elapsed) or elapsed < 0:
            return
        if elapsed > self.MAX_SECONDS:
            self.truncated = True
            return
        if self.frames and elapsed - self.frames[-1][0] < 1 / self.FPS:
            return
        height, width = frame.shape[:2]
        size = (min(640, width) // 2 * 2, max(2, round(height * min(640, width) / width) // 2 * 2))
        small = cv2.resize(frame, size)
        ok, encoded = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if not ok:
            return
        payload = encoded.tobytes()
        if self.buffer_bytes + len(payload) > self.MAX_BUFFER_BYTES:
            self.truncated = True
            return
        self.frames.append((elapsed, payload))
        self.buffer_bytes += len(payload)

    def finish(self, history_id, score, duration):
        frames, truncated = self.frames, self.truncated
        self.reset()
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
            self.publish(history_id, payload, clip_duration, truncated or duration > self.MAX_SECONDS)
        except Exception:
            # Recording is optional: never stop tracking, serial scores or history.
            self.publish(history_id, None, 0, False)
        finally:
            self._encoding.release()

    @classmethod
    def encode(cls, frames, score, duration):
        frames = [(t, data) for t, data in frames if t <= duration]
        if not frames:
            raise ValueError("No visible flight frames")
        first = cv2.imdecode(np.frombuffer(frames[0][1], np.uint8), cv2.IMREAD_COLOR)
        if first is None:
            raise ValueError("Invalid video frame")
        height, width = first.shape[:2]
        clip_duration = min(duration, cls.MAX_SECONDS, frames[-1][0] + 1 / cls.FPS)
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
        self.reset()
        self._worker.shutdown(wait=True)
