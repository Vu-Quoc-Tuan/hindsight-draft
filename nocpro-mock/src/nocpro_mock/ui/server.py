"""Small read-only HTTP surface for the topology navigation model."""

from __future__ import annotations

import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ..data_profiles import dataset_profiles
from .topology_api import projection_payload


def _integer(value: str | None, default: int, *, minimum: int, maximum: int) -> int:
    try:
        result = int(value) if value is not None else default
    except ValueError:
        return default
    return min(max(result, minimum), maximum)


class TopologyRequestHandler(BaseHTTPRequestHandler):
    def _json(self, status: HTTPStatus, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            # A browser/navigation client may cancel a bounded read while the
            # local server is writing. It is not a topology-model failure.
            return

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/topology/profiles":
            self._json(HTTPStatus.OK, {"profiles": [profile.__dict__ for profile in dataset_profiles()]})
            return
        if parsed.path != "/api/topology/projection":
            self._json(HTTPStatus.NOT_FOUND, {"error": "endpoint not found"})
            return
        query = parse_qs(parsed.query)
        profile = query.get("profile_id", [None])[0]
        if profile is None:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "profile_id is required"})
            return
        try:
            payload = projection_payload(
                profile,
                root_id=query.get("root_id", [None])[0],
                source_root=getattr(self.server, "source_root", None),
                max_depth=_integer(query.get("depth", [None])[0], 3, minimum=0, maximum=8),
                max_children=_integer(query.get("child_limit", [None])[0], 50, minimum=1, maximum=200),
            )
        except ValueError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        self._json(HTTPStatus.OK, payload)

    def log_message(self, _format: str, *_args: object) -> None:
        """Keep library tests and embedding services quiet by default."""


def create_topology_server(host: str = "127.0.0.1", port: int = 0, *, source_root: str | Path | None = None) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), TopologyRequestHandler)
    server.source_root = str(source_root) if source_root is not None else None  # type: ignore[attr-defined]
    return server


def start_topology_server_in_thread(host: str = "127.0.0.1", port: int = 0, *, source_root: str | Path | None = None) -> tuple[ThreadingHTTPServer, str]:
    server = create_topology_server(host, port, source_root=source_root)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://{host}:{server.server_port}"
