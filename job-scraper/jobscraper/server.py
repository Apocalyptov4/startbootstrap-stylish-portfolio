"""Local web app: `python -m jobscraper ui` opens the job browser in your web browser.

Uses only the standard library HTTP server. Everything the app remembers
(settings, fetched jobs, saved/applied/hidden marks) is kept as small JSON
files in the data directory, ~/.jobscraper by default.
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import sys
import threading
import webbrowser
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import demo, geo
from .config import DEFAULT_CONFIG, public_config, validate_config  # noqa: F401 (re-exported)
from .scraper import Filters, add_coordinates, carry_over, dedupe, run
from .sources import build_sources
from .state import SeenStore

log = logging.getLogger("jobscraper")

WEB_DIR = Path(__file__).parent / "web"
STATIC = {
    "/": (WEB_DIR / "index.html", "text/html; charset=utf-8"),
    "/app.js": (WEB_DIR / "app.js", "text/javascript; charset=utf-8"),
    "/style.css": (WEB_DIR / "style.css", "text/css; charset=utf-8"),
    "/places.json": (geo.PLACES_FILE, "application/json; charset=utf-8"),
}
STATUSES = {"saved", "applied", "hidden"}
FORGET_AFTER_DAYS = 90


class Store:
    """The app's persistent state, backed by JSON files in `data_dir`."""

    def __init__(self, data_dir: Path, demo_mode: bool = False, session=None):
        self.dir = Path(data_dir) / ("demo" if demo_mode else "")
        self.dir.mkdir(parents=True, exist_ok=True)
        self.demo = demo_mode
        self.session = session  # injectable for tests
        self.lock = threading.Lock()
        self.refresh_lock = threading.Lock()
        self.refreshing = False
        try:
            self.config = validate_config(self._load("config.json", DEFAULT_CONFIG))
        except ValueError:
            log.warning("Saved settings were invalid; starting from the defaults.")
            self.config = validate_config(DEFAULT_CONFIG)
        self.tracking: dict[str, dict] = self._load("tracking.json", {})
        self.cache: dict | None = self._load("jobs.json", None)

    def _load(self, name, default):
        try:
            return json.loads((self.dir / name).read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return copy.deepcopy(default)

    def _save(self, name, data):
        tmp = self.dir / f"{name}.tmp"
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.dir / name)

    # --- API operations -------------------------------------------------

    def state(self) -> dict:
        with self.lock:
            cache = self.cache or {"jobs": [], "fetched_at": None, "errors": {}, "fetched": 0, "sources": []}
            jobs = [{**j, "status": self.tracking.get(j["key"], {}).get("status")} for j in cache["jobs"]]
            return {
                **cache,
                "jobs": jobs,
                "config": public_config(self.config),
                "demo": self.demo,
                "refreshing": self.refreshing,
            }

    def set_config(self, cfg: dict) -> dict:
        with self.lock:
            cfg = validate_config(cfg, previous=self.config)
            self.config = cfg
            self._save("config.json", cfg)
        return public_config(cfg)

    def set_status(self, key: str, status: str | None) -> None:
        if status is not None and status not in STATUSES:
            raise ValueError(f"status must be one of {sorted(STATUSES)} or null")
        with self.lock:
            entry = self.tracking.setdefault(key, {})
            if status:
                entry["status"] = status
            else:
                entry.pop("status", None)
            self._save("tracking.json", self.tracking)

    def refresh(self) -> dict:
        with self.refresh_lock:
            self.refreshing = True
            try:
                if self.demo:
                    raw = demo.jobs()
                    jobs, fetched, errors, labels = dedupe(raw), len(raw), {}, ["demo"]
                    add_coordinates(jobs)
                else:
                    sources = build_sources(self.config)
                    result = run(sources, Filters(), session=self.session)
                    jobs, fetched, errors = result.jobs, result.fetched, result.errors
                    labels = [s.label for s in sources]
                self._store_results(jobs, fetched, errors, labels)
            finally:
                self.refreshing = False
        return self.state()

    def _store_results(self, jobs, fetched, errors, labels):
        now = datetime.now(timezone.utc).isoformat()
        with self.lock:
            previous = (self.cache or {}).get("fetched_at")
            out = []
            for j in jobs:
                key = SeenStore.key(j)
                t = self.tracking.setdefault(key, {})
                first_seen = t.setdefault("first_seen", now)
                t["last_seen"] = now
                # "New" = appeared since the previous refresh (nothing is new on the very first one).
                out.append({**j.to_dict(), "key": key, "is_new": bool(previous) and first_seen > previous})
            # Keep recent area-search jobs from earlier refreshes: each refresh only gets the newest few hundred.
            carried = carry_over(out, (self.cache or {}).get("jobs") or [], self.config.get("areas") or [])
            for j in carried[len(out):]:
                j["is_new"] = False
                j.pop("status", None)
                self.tracking.setdefault(j["key"], {})["last_seen"] = now
            out = carried
            cutoff = (datetime.now(timezone.utc) - timedelta(days=FORGET_AFTER_DAYS)).isoformat()
            self.tracking = {
                k: v for k, v in self.tracking.items() if v.get("status") or v.get("last_seen", now) >= cutoff
            }
            self.cache = {"jobs": out, "fetched_at": now, "fetched": fetched, "errors": errors, "sources": labels}
            self._save("jobs.json", self.cache)
            self._save("tracking.json", self.tracking)


class Handler(BaseHTTPRequestHandler):
    store: Store  # set on the subclass created in make_server
    server_version = "jobscraper"

    def log_message(self, fmt, *args):
        log.debug("%s - " + fmt, self.address_string(), *args)

    def _send(self, status: int, body: bytes, ctype: str):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, status: int = 200):
        self._send(status, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _error(self, status: int, message: str):
        self._json({"error": message}, status)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > 1_000_000:
            raise ValueError("request too large")
        return json.loads(self.rfile.read(length) or b"null")

    def _same_origin(self) -> bool:
        # Stops other websites open in your browser from changing the app's data.
        origin = self.headers.get("Origin")
        return origin is None or urlparse(origin).netloc == self.headers.get("Host")

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/state":
            return self._json(self.store.state())
        if path in STATIC:
            file, ctype = STATIC[path]
            return self._send(200, file.read_bytes(), ctype)
        self._error(HTTPStatus.NOT_FOUND, "not found")

    def do_POST(self):
        self._write("POST")

    def do_PUT(self):
        self._write("PUT")

    def _write(self, method: str):
        path = urlparse(self.path).path
        if not self._same_origin():
            return self._error(HTTPStatus.FORBIDDEN, "cross-origin request refused")
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            return self._error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "expected application/json")
        try:
            body = self._body()
            if method == "POST" and path == "/api/refresh":
                return self._json(self.store.refresh())
            if method == "PUT" and path == "/api/config":
                return self._json(self.store.set_config(body))
            if method == "POST" and path == "/api/status":
                if not isinstance(body, dict) or not isinstance(body.get("key"), str):
                    raise ValueError("expected {key, status}")
                self.store.set_status(body["key"], body.get("status"))
                return self._json({"ok": True})
        except (ValueError, json.JSONDecodeError) as e:
            return self._error(HTTPStatus.BAD_REQUEST, str(e))
        self._error(HTTPStatus.NOT_FOUND, "not found")


def make_server(store: Store, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"store": store})
    return ThreadingHTTPServer((host, port), handler)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="jobscraper ui", description="Open the job browser in your web browser.")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to reach it from other devices (no login!)")
    p.add_argument("--data-dir", default=str(Path.home() / ".jobscraper"), help="where settings and jobs are saved")
    p.add_argument("--demo", action="store_true", help="show made-up sample jobs instead of fetching real ones")
    p.add_argument("--no-browser", action="store_true", help="don't open a browser tab automatically")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    logging.getLogger("urllib3").setLevel(logging.ERROR)

    url = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '') else args.host}:{args.port}/"
    store = Store(Path(args.data_dir), demo_mode=args.demo)
    try:
        server = make_server(store, args.host, args.port)
    except OSError as e:
        if _already_running(url):
            # Double-clicked a second time: just bring up the copy that's already running.
            print(f"Job Radar is already running at {url}", file=sys.stderr)
            if not args.no_browser:
                webbrowser.open(url)
            return 0
        print(f"Could not start on port {args.port} ({e}). Try --port 8766.", file=sys.stderr)
        return 1
    if getattr(sys, "frozen", False):
        print(f"Job Radar is running at {url}\nKeep this window open while you use it. Close it to quit.", file=sys.stderr)
    else:
        print(f"Job Radar is running at {url}  (press Ctrl+C to stop)", file=sys.stderr)
    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, [url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
    finally:
        server.server_close()
    return 0


def _already_running(url: str) -> bool:
    import urllib.request

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url + "api/state", timeout=2) as r:
            return "config" in json.loads(r.read())
    except Exception:
        return False
