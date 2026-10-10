"""
Local web dashboard for the desk assistant robot.

    python3 dashboard/server.py              # on the Pi, real hardware
    python3 dashboard/server.py --sim        # anywhere, simulated robot
    python3 dashboard/server.py --host 0.0.0.0   # reachable from other devices on the LAN

Standard library only (plus gpiozero on the Pi). Open http://localhost:8000
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from robot import GpioHardware, Robot, SimHardware

STATIC_DIR = Path(__file__).resolve().parent / "static"

# Only these files are served - no directory browsing, no path traversal.
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/static/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
}


class Handler(BaseHTTPRequestHandler):
    robot: Robot = None
    server_version = "DeskRobot/1.0"

    def log_message(self, fmt, *args):
        pass  # the page polls several times a second; keep the terminal readable

    def _send(self, status, body: bytes, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status, payload):
        self._send(status, json.dumps(payload).encode(), "application/json")

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/state":
            return self._json(200, self.robot.snapshot())
        entry = STATIC_FILES.get(path)
        if not entry:
            return self._json(404, {"error": "Not found"})
        name, content_type = entry
        self._send(200, (STATIC_DIR / name).read_bytes(), content_type)

    def do_POST(self):
        path = self.path.split("?", 1)[0]

        # Requiring a JSON content type means a random web page in the same browser
        # can't trigger moves with a plain form post (it would need a CORS preflight).
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            return self._json(415, {"error": "Content-Type must be application/json"})

        length = int(self.headers.get("Content-Length") or 0)
        if length > 10_000:
            return self._json(413, {"error": "Request too large"})
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json(400, {"error": "Invalid JSON"})

        try:
            if path == "/api/move":
                self.robot.move(body.get("direction"), body.get("duration"))
            elif path == "/api/stop":
                self.robot.stop()
            elif path == "/api/settings":
                self.robot.update_settings(speed=body.get("speed"), stop_distance=body.get("stop_distance"))
            elif path == "/api/sim/reset":
                self.robot.reset_sim()
            else:
                return self._json(404, {"error": "Not found"})
        except ValueError as exc:
            return self._json(400, {"error": str(exc)})

        self._json(200, self.robot.snapshot())


    def _read_json(self):
        """Shared POST validation for subclasses. Returns the body, or None after sending an error."""
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            self._json(415, {"error": "Content-Type must be application/json"})
            return None
        length = int(self.headers.get("Content-Length") or 0)
        if length > 10_000:
            self._json(413, {"error": "Request too large"})
            return None
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._json(400, {"error": "Invalid JSON"})
            return None


def parse_args(description="Desk assistant robot dashboard"):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--sim", action="store_true", help="use the simulated robot instead of GPIO hardware")
    parser.add_argument("--host", default="127.0.0.1", help="address to bind (default: 127.0.0.1, this machine only)")
    parser.add_argument("--port", type=int, default=8000, help="port (default: 8000)")
    return parser.parse_args()


def make_robot(args):
    if args.sim:
        hardware = SimHardware()
    else:
        try:
            hardware = GpioHardware()
        except Exception as exc:
            print(f"Could not open the GPIO hardware: {exc}")
            print("Not on the Pi? Run with --sim to use the simulated robot.")
            sys.exit(1)
    return Robot(hardware)


def serve(args, robot, handler_cls, on_close=None):
    handler_cls.robot = robot
    server = ThreadingHTTPServer((args.host, args.port), handler_cls)
    server.daemon_threads = True

    shown_host = "localhost" if args.host in ("127.0.0.1", "0.0.0.0") else args.host
    print(f"Dashboard running at http://{shown_host}:{args.port}  ({robot.hw.mode})")
    if args.host == "0.0.0.0":
        print("Listening on all interfaces - anyone on this network can drive the robot.")
    print("Ctrl+C to stop the robot and quit.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nEmergency stop requested.")
    finally:
        server.server_close()
        if on_close:
            on_close()
        robot.close()
        print("All motors stopped. Robot closed.")


def main():
    args = parse_args()
    serve(args, make_robot(args), Handler)


if __name__ == "__main__":
    main()
