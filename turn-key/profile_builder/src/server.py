#!/usr/bin/env python3
"""Minimal HTTP server for profile persistence in turn-key-profile/."""

import http.server
import json
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent


def _read_base_path() -> Path:
    """Read base path from data/.base_path (relative to the project root).

    Returns the content of data/.base_path as a Path, stripped of whitespace.
    Falls back to PROJECT_ROOT if the file is missing or empty.
    """
    base_file = PROJECT_ROOT / "data" / ".base_path"
    if base_file.exists():
        return Path(base_file.read_text().strip())
    return PROJECT_ROOT


BASE_PATH = _read_base_path()
PROFILES_DIR = BASE_PATH / "turn-key-profile"


class ProfileHandler(http.server.BaseHTTPRequestHandler):
    """Handle profile save, load, list, and delete operations."""

    def _send_json(self, status: int, data: dict) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == "/api/profiles/list":
            PROFILES_DIR.mkdir(parents=True, exist_ok=True)
            files = sorted(f.name for f in PROFILES_DIR.glob("*.json"))
            self._send_json(200, {"profiles": files})

        elif path == "/api/profiles/path":
            self._send_json(200, {"path": str(PROFILES_DIR)})

        elif path == "/api/profiles/load":
            name = params.get("name", [None])[0]
            if not name:
                self._send_json(400, {"error": "Missing name parameter"})
                return
            filepath = PROFILES_DIR / name
            if not filepath.exists():
                self._send_json(404, {"error": f"Profile {name} not found"})
                return
            data = json.loads(filepath.read_text())
            self._send_json(200, data)

        else:
            self._send_json(404, {"error": "Not found"})

    def do_POST(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/profiles/save":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)

            filename = data.get("name", "default.json")
            profile = data.get("profile", {})

            # Create directory if missing (hard gate requirement)
            PROFILES_DIR.mkdir(parents=True, exist_ok=True)
            filepath = PROFILES_DIR / filename

            # Write profile (filename is profile name only, no timestamp)
            filepath.write_text(json.dumps(profile, indent=2))

            self._send_json(200, {"status": "ok", "path": str(filepath)})

        else:
            self._send_json(404, {"error": "Not found"})

    def do_DELETE(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if parsed.path == "/api/profiles/delete":
            name = params.get("name", [None])[0]
            if not name:
                self._send_json(400, {"error": "Missing name parameter"})
                return

            filepath = PROFILES_DIR / name
            if not filepath.exists():
                self._send_json(404, {"error": f"Profile {name} not found"})
                return

            filepath.unlink()
            self._send_json(200, {"status": "deleted"})
        else:
            self._send_json(404, {"error": "Not found"})

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass


def main():
    """Start the profile server."""
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080

    # Create profiles directory if missing
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Profile server running on http://localhost:{port}")
    print(f"Profiles directory: {PROFILES_DIR.absolute()}")

    server = http.server.HTTPServer(("0.0.0.0", port), ProfileHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.server_close()


if __name__ == "__main__":
    main()
