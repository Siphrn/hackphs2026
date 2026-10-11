import unittest
from unittest.mock import patch

import cv2
import numpy as np

from flight_recording import FlightRecorder


class RecordingTests(unittest.TestCase):
    def test_capture_rate_size_and_duration_limits(self):
        recorder = FlightRecorder(lambda *args: None)
        frame = np.zeros((480, 800, 3), np.uint8)
        recorder.capture(frame, 0)
        recorder.capture(frame, .01)
        self.assertEqual(len(recorder.frames), 1)
        decoded = cv2.imdecode(np.frombuffer(recorder.frames[0][1], np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(decoded.shape[1], 640)
        recorder.capture(frame, 16)
        self.assertTrue(recorder.truncated)
        recorder.reset()
        recorder.MAX_BUFFER_BYTES = 1
        recorder.capture(frame, 0)
        self.assertTrue(recorder.truncated)
        self.assertEqual(recorder.buffer_bytes, 0)
        recorder.close()

    def test_background_encoding_and_missing_history(self):
        results = []
        recorder = FlightRecorder(lambda *args: results.append(args))
        frame = np.zeros((240, 320, 3), np.uint8)
        recorder.capture(frame, 0)
        recorder.finish(None, 42, 1)
        self.assertEqual(results, [])
        recorder.capture(frame, 0)
        with patch.object(recorder, "encode", return_value=(b"encoded-mp4", 1)) as encoder:
            recorder.finish("history-1", 86, 1)
            recorder.close()
        self.assertEqual(results, [("history-1", b"encoded-mp4", 1, False)])
        self.assertEqual(encoder.call_args.args[1], 86)
        self.assertEqual(recorder.frames, [])

    def test_encoder_failure_is_optional(self):
        results = []
        recorder = FlightRecorder(lambda *args: results.append(args))
        recorder.capture(np.zeros((240, 320, 3), np.uint8), 0)
        with patch.object(recorder, "encode", side_effect=RuntimeError("No codec")):
            recorder.finish("history-1", 86, 1)
            recorder.close()
        self.assertEqual(results, [("history-1", None, 0, False)])

    def test_real_h264_output(self):
        recorder = FlightRecorder(lambda *args: None)
        for index in range(21):
            frame = np.zeros((360, 640, 3), np.uint8)
            cv2.circle(frame, (30 + index * 20, 150), 15, (0, 255, 255), -1)
            recorder.capture(frame, index / 20 + index * .00001)
        try:
            payload, duration = recorder.encode(recorder.frames, 91, 1)
        except RuntimeError:
            self.skipTest("H.264 encoder not installed; graceful fallback tested separately")
        finally:
            recorder.close()
        self.assertIn(b"ftyp", payload[:32])
        self.assertGreater(len(payload), 1000)
        self.assertLessEqual(duration, 1.05)


if __name__ == "__main__":
    unittest.main()
