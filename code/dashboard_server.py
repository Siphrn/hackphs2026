import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


WEB_DIRECTORY = Path(__file__).parent.parent / "web"


class DashboardState:
    def __init__(self):
        self._lock = threading.Lock()
        self._data = {
            "status": "READY",
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
            "prediction": [],
        }

    def update(self, **values):
        with self._lock:
            self._data.update(values)

    def snapshot(self):
        with self._lock:
            return dict(self._data)


dashboard_state = DashboardState()


class DashboardRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/state":
            payload = json.dumps(dashboard_state.snapshot()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
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
