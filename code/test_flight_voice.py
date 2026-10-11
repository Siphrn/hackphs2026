import os
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from dashboard_server import DashboardState
from flight_voice import FlightVoice, score_commentary


class VoiceTests(unittest.TestCase):
    def test_tiers_and_clamping(self):
        for score, expected in [(0, "try again"), (24, "try again"), (25, "bumpy"),
                                (49, "bumpy"), (50, "Nice effort"), (74, "Nice effort"),
                                (75, "Great flight"), (89, "Great flight"),
                                (90, "Outstanding"), (100, "Outstanding")]:
            self.assertIn(expected, score_commentary(score))
            self.assertIn(f"{score} out of 100", score_commentary(score))
        self.assertIn("100 out of 100", score_commentary(110))

    def test_completed_transition_only(self):
        state = DashboardState()
        state.update(status="COMPLETE")
        state.update(status="COMPLETE")
        self.assertEqual(state.snapshot()["flight_id"], 1)
        state.update(status="ARMED")
        state.update(status="COMPLETE")
        self.assertEqual(state.snapshot()["flight_id"], 2)

    def test_completed_result_is_frozen_and_copied(self):
        state = DashboardState()
        points = [[10, 20], [30, 40]]
        state.update(status="COMPLETE", score=73, trajectory=points)
        points[0][0] = 999
        state.update(status="COMPLETE", score=12, trajectory=[])
        result = state.snapshot()
        self.assertEqual(result["score"], 73)
        self.assertEqual(result["trajectory"][0][0], 10)
        result["trajectory"].clear()
        self.assertEqual(len(state.snapshot()["trajectory"]), 2)

    def test_audio_urls_are_unique_after_restart(self):
        a, b = FlightVoice(), FlightVoice()
        self.assertNotEqual(a.session_id, b.session_id)

    def test_deduplicate_and_hide_audio(self):
        voice = FlightVoice()
        finished = threading.Event()
        with patch.object(voice, "_generate", side_effect=lambda _: finished.set()) as generate:
            voice.request(1, 95)
            self.assertTrue(finished.wait(2))
            voice.request(1, 95)
            self.assertEqual(generate.call_count, 1)
        voice._records[1]["audio"] = b"audio"
        self.assertNotIn("audio", voice.public_snapshot(1))

    def test_missing_key(self):
        voice = FlightVoice()
        voice._records[1] = {"text": "Test"}
        with patch.dict(os.environ, {"ELEVENLABS_API_KEY": ""}), patch("flight_voice.keychain_api_key", return_value=""):
            voice._generate(1)
            self.assertEqual(voice.snapshot(1)["status"], "error")
            self.assertFalse(voice.snapshot(1)["configured"])

    def test_keychain_fallback(self):
        with patch.dict(os.environ, {"ELEVENLABS_API_KEY": ""}), patch("flight_voice.keychain_api_key", return_value="stored-secret"):
            from flight_voice import get_api_key
            self.assertEqual(get_api_key(), "stored-secret")
            self.assertTrue(FlightVoice().snapshot(1)["configured"])

    def test_provider_success_and_error(self):
        voice = FlightVoice()
        voice._records[1] = {"text": "Test"}
        with patch.dict(os.environ, {"ELEVENLABS_API_KEY": "test-secret"}):
            with patch("flight_voice.urlopen") as open_url:
                open_url.return_value.__enter__.return_value.read.return_value = b"fake-mp3"
                voice._generate(1)
                self.assertEqual(voice.audio(1), b"fake-mp3")
                self.assertNotIn("test-secret", str(voice.public_snapshot(1)))
            with patch("flight_voice.urlopen", side_effect=HTTPError("url", 403, "Forbidden", {}, None)):
                voice._generate(1)
                self.assertEqual(voice.snapshot(1)["status"], "error")
                self.assertIn("permission", voice.snapshot(1)["error"])


if __name__ == "__main__":
    unittest.main()
