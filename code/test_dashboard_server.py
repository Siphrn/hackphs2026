import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import dashboard_server as dashboard
from flight_voice import FlightVoice
from flight_history import FlightHistory


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.state = dashboard.DashboardState(FlightHistory())
        self.voice = FlightVoice()
        self.patches = [patch.object(dashboard, "dashboard_state", self.state),
                        patch.object(dashboard, "flight_voice", self.voice),
                        patch("flight_voice.get_api_key", return_value="test-key")]
        for item in self.patches:
            item.start()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), dashboard.DashboardRequestHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        for item in reversed(self.patches):
            item.stop()

    def request(self, method, path, body=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        connection.request(method, path, body=json.dumps(body) if body is not None else None)
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def test_stale_score_or_session_cannot_generate_audio(self):
        self.state.update(status="COMPLETE", score=73)
        result = dict(flight_id=1, score=73, session_id=self.voice.session_id)
        with patch.object(self.voice, "request") as generate:
            self.assertEqual(self.request("POST", "/api/voice", dict(result, score=42))[0], 409)
            self.assertEqual(self.request("POST", "/api/voice", dict(result, session_id="old"))[0], 409)
            self.assertEqual(self.request("POST", "/api/voice", dict(result, flight_id=9))[0], 409)
            self.assertEqual(self.request("POST", "/api/voice", result)[0], 202)
            generate.assert_called_once_with(1, 73)

    def test_audio_is_not_cached_and_old_sessions_rejected(self):
        self.voice._records[1] = {"audio": b"test-audio", "status": "ready"}
        status, headers, audio = self.request("GET", f"/api/voice/{self.voice.session_id}/1.mp3")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(audio, b"test-audio")
        self.assertEqual(self.request("GET", "/api/voice/old-session/1.mp3")[0], 404)

    def test_history_endpoint(self):
        saved = [{"history_id":"saved-flight", "score":83, "trajectory":[[10,20],[30,40]], "trajectory_times":[0,.5]}]
        with patch.object(self.state, "history", return_value=saved):
            status, headers, payload = self.request("GET", "/api/history")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(json.loads(payload)["flights"], saved)

    def test_rename_endpoint(self):
        self.state.update(status="COMPLETE", airtime=1, score=83)
        identifier = self.state.history()[0]["history_id"]
        body = dict(history_id=identifier, name="My glider", session_id=self.voice.session_id)
        self.assertEqual(self.request("POST", "/api/history/rename", body)[0], 200)
        self.assertEqual(self.state.history()[0]["name"], "My glider")
        self.assertEqual(self.request("POST", "/api/history/rename", dict(body, name=""))[0], 400)
        self.assertEqual(self.request("POST", "/api/history/rename", dict(body, session_id="old"))[0], 409)
        self.assertEqual(self.request("POST", "/api/history/rename", dict(body, history_id="gone"))[0], 404)


if __name__ == "__main__":
    unittest.main()
