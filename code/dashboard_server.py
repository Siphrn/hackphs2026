import json
import copy
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from flight_voice import FlightVoice, score_commentary
from flight_history import FlightHistory


WEB_DIRECTORY = Path(__file__).parent.parent / "web"


class DashboardState:
    def __init__(self, history_store=None):
        self._lock = threading.Lock()
        self._history_store = history_store
        self._data = {
            "status": "READY",
            "flight_id": 0,
            "history_id": None,
            "history_error": False,
            "detected": False,
            "score": 0,
            "airtime": 0,
            "path_length": 0,
            "horizontal_distance": 0,
            "smoothness": 0,
            "speed": 0,
            "angle": 0,
            "remaining_airtime": 0,
            "projected_distance": 0,
            "landing_x": None,
            "prediction_confidence": 0,
            "frame_width": 640,
            "frame_height": 480,
            "trajectory": [],
            "trajectory_times": [],
            "prediction": [],
            "forecast_endpoint": None,
            "forecast_kind": None,
        }

    def update(self, **values):
        with self._lock:
            if values.get("status") == "COMPLETE" and self._data["status"] != "COMPLETE":
                self._data["flight_id"] += 1
            # A completed result is immutable until the tracker leaves COMPLETE.
            if self._data["status"] == "COMPLETE" and values.get("status") == "COMPLETE":
                return
            self._data.update(copy.deepcopy(values))
            if values.get("status") == "COMPLETE" and self._history_store is not None:
                try:
                    self._data["history_id"] = self._history_store.save(self._data)
                    self._data["history_error"] = False
                except OSError:
                    self._data["history_error"] = True
                    print("Could not save flight history. Tracking continues.")

    def snapshot(self):
        with self._lock:
            return copy.deepcopy(self._data)

    def history(self):
        return self._history_store.list() if self._history_store else []

    def rename_flight(self, history_id, name):
        if self._history_store is None:
            raise KeyError(history_id)
        return self._history_store.rename(history_id, name)


dashboard_state = DashboardState(FlightHistory())
flight_voice = FlightVoice()


class DashboardRequestHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path not in ("/api/voice", "/api/history/rename"):
            self.send_error(404)
            return
        # Do not let unrelated websites trigger paid speech requests on localhost.
        origin = self.headers.get("Origin")
        if origin and urlsplit(origin).netloc != self.headers.get("Host"):
            self.send_error(403)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1024:
                raise ValueError("Invalid body size")
            requested = json.loads(self.rfile.read(length))
            if not isinstance(requested, dict):
                raise ValueError("Invalid body")
        except (ValueError, json.JSONDecodeError):
            self.send_error(400, "Expected flight identity")
            return
        if self.path == "/api/history/rename":
            if requested.get("session_id") != flight_voice.session_id:
                self.send_error(409, "Tracker session changed")
                return
            try:
                name = dashboard_state.rename_flight(requested.get("history_id"), requested.get("name"))
            except ValueError:
                self.send_error(400, "Use a flight name between 1 and 60 characters")
                return
            except KeyError:
                self.send_error(404, "Flight no longer in history")
                return
            payload = json.dumps({"name": name}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        state = dashboard_state.snapshot()
        if state["status"] != "COMPLETE":
            self.send_error(409, "Finish a flight first")
            return
        if (requested.get("flight_id") != state["flight_id"]
                or requested.get("session_id") != flight_voice.session_id
                or requested.get("score") != state["score"]):
            self.send_error(409, "Flight result changed")
            return
        flight_voice.request(state["flight_id"], state["score"])
        self.send_response(202)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if self.path == "/api/history":
            try:
                payload = json.dumps({"flights": dashboard_state.history()}).encode("utf-8")
            except OSError:
                self.send_error(503, "History unavailable")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if self.path == "/api/state":
            state = dashboard_state.snapshot()
            state["session_id"] = flight_voice.session_id
            state["voice"] = flight_voice.public_snapshot(state["flight_id"])
            if state["status"] == "COMPLETE":
                state["voice"].setdefault("text", score_commentary(state["score"]))
            payload = json.dumps(state).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if self.path.startswith("/api/voice/") and self.path.endswith(".mp3"):
            try:
                session_id, filename = self.path.removeprefix("/api/voice/").split("/")
                if session_id != flight_voice.session_id:
                    raise ValueError("Old audio session")
                flight_id = int(filename.removesuffix(".mp3"))
            except ValueError:
                self.send_error(404)
                return
            payload = flight_voice.audio(flight_id)
            if payload is None:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)
            return

        if self.path == "/health":
            payload = b'{"ok": true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if self.path in ("/", "/index.html"):
            index_path = WEB_DIRECTORY / "index.html"
            try:
                payload = index_path.read_bytes()
            except FileNotFoundError:
                self.send_error(404, "Dashboard file not found")
                return

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        self.send_error(404)

    def log_message(self, format, *args):
        return


def start_dashboard_server(port=8000):
    requested_port = port
    while True:
        try:
            server = ThreadingHTTPServer(("0.0.0.0", port), DashboardRequestHandler)
            break
        except OSError:
            port += 1
            if port > requested_port + 9:
                raise

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"Dashboard: http://localhost:{port}")
    print("For laptop 2, replace localhost with this laptop's local IP address.")
    return server
