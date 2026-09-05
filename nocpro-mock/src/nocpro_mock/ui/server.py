"""HTTP Server and REST API for nocpro-mock Web UI.

Zero external dependencies: uses Python stdlib (http.server + asyncio).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer, SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse

from ..config import load_config
from ..data_profiles import dataset_profiles
from .topology_api import projection_payload, resolve_navigation_payload, search_payload
from ..contract import (
    ContractViolation,
    MockSnapshotPackage,
    package_to_json,
    parse_package,
    validate_package,
)
from ..fixtures.golden import load_golden_fixture
from ..loaders.topology_ip_csv import TopoIPLoader
from ..producer.kafka_snapshot import KafkaSnapshotConfig, publish_snapshot
from ..replay.snapshot import build_golden_snapshot, build_real_replay_snapshot
from ..scenarios.sequence import load_sequence_manifest

logger = logging.getLogger(__name__)

MOCK_ROOT = Path(__file__).resolve().parents[3]
WORKSPACE_ROOT = MOCK_ROOT.parent
ASSETS_DIR = Path(__file__).parent / "assets"

DEFAULT_ALARM_CSV = "datasets/raw/alarm/alarm_data.csv"
DEFAULT_TOPO_IP_CSV = "datasets/raw/topo/topoIP.csv"
DEFAULT_SYNTHETIC_DIR = "docs/examples/synthetic"
MAX_REQUEST_BODY_BYTES = 1 * 1024 * 1024
MAX_CHUNK_TARGET_BYTES = 4 * 1024 * 1024
DEFAULT_KAFKA_TOPIC = "nocpro.snapshot.v1"


def _allowed_input_roots() -> tuple[Path, ...]:
    """Return the only directories a browser request may select input from.

    The Mock UI is deliberately a dataset/fixture replay tool. A request must
    never turn it into a generic filesystem reader merely by supplying an
    absolute path. The roots are intentionally narrow rather than the whole
    workspace because the sibling Explain service may contain local secrets.
    """
    return (
        (MOCK_ROOT / "datasets").resolve(),
        (MOCK_ROOT / "docs" / "examples" / "synthetic").resolve(),
        (MOCK_ROOT / "docs" / "examples" / "golden_2214039").resolve(),
    )


def _resolve_path(rel_or_abs: str | Path) -> Path:
    """Resolve an input selected by the UI within approved dataset roots."""
    raw = Path(rel_or_abs)
    candidate = raw if raw.is_absolute() else MOCK_ROOT / raw
    resolved = candidate.resolve(strict=False)
    if not any(resolved.is_relative_to(root) for root in _allowed_input_roots()):
        raise ValueError("Requested input path is outside approved Mock datasets or fixtures")
    return resolved


def _resolve_sequence_snapshot(sequence_path: Path, snapshot_name: object) -> Path:
    """Resolve a browser-selected sequence member without allowing path escape."""
    if sequence_path.exists() and not sequence_path.is_dir():
        if snapshot_name not in (None, "", "snapshot_000.json"):
            raise ValueError("sequence_snapshot requires a sequence directory")
        return sequence_path
    if not isinstance(snapshot_name, str) or not snapshot_name:
        raise ValueError("sequence_snapshot must be a relative file name")
    child = Path(snapshot_name)
    if child.is_absolute() or child.name != snapshot_name:
        raise ValueError("sequence_snapshot must be a relative file name")
    return _resolve_path(sequence_path / child)


def _chunk_target_bytes(value: object) -> int:
    """Validate the browser's chunk hint before preview or publish uses it."""
    if isinstance(value, bool):
        raise ValueError("chunk_target_bytes must be an integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("chunk_target_bytes must be an integer") from exc
    if not 1 <= result <= MAX_CHUNK_TARGET_BYTES:
        raise ValueError(
            f"chunk_target_bytes must be between 1 and {MAX_CHUNK_TARGET_BYTES}"
        )
    return result


def _discover_sequences() -> list[dict[str, Any]]:
    syn_dir = _resolve_path(DEFAULT_SYNTHETIC_DIR)
    if not syn_dir.is_dir():
        return []

    sequences = []
    for item in sorted(syn_dir.iterdir()):
        if item.is_dir() and (item / "sequence.yaml").is_file():
            try:
                manifest = load_sequence_manifest(item / "sequence.yaml")
                sequences.append(
                    {
                        "id": item.name,
                        "name": item.name.replace("_", " ").title(),
                        "path": str(item.relative_to(MOCK_ROOT) if item.is_relative_to(MOCK_ROOT) else item),
                        "sequence_type": manifest.sequence_type.value,
                        "snapshots": list(manifest.snapshots),
                        "history_snapshots": list(manifest.history_snapshots),
                        "target_snapshot": manifest.target_snapshot,
                    }
                )
            except Exception as e:
                logger.debug("Failed loading manifest %s: %s", item, e)
    return sequences


def check_kafka_socket(bootstrap: str, timeout: float = 2.0) -> tuple[bool, str]:
    try:
        # If multiple servers comma-separated, test the first
        target = bootstrap.split(",")[0].strip()
        if ":" in target:
            host, port_str = target.split(":", 1)
            port = int(port_str)
        else:
            host = target
            port = 9092
        with socket.create_connection((host, port), timeout=timeout):
            return True, f"Successfully connected to {host}:{port}"
    except Exception as exc:
        return False, str(exc)


def build_package_from_request(data: dict[str, Any]) -> MockSnapshotPackage:
    mode = data.get("mode", "real")
    snapshot_id = data.get("snapshot_id", "snapshot_replay_001")
    snapshot_version = str(data.get("snapshot_version", "1"))
    config = load_config()

    if mode == "golden":
        fixture_dir = data.get("fixture_dir")
        topo_path = _resolve_path(data.get("topo_ip", DEFAULT_TOPO_IP_CSV))
        device_codes: set[str] = set()
        if data.get("with_topology") and topo_path.is_file():
            device_codes = TopoIPLoader(topo_path).device_codes()
        return build_golden_snapshot(
            config=config,
            fixture=load_golden_fixture(
                _resolve_path(fixture_dir) if fixture_dir is not None else None
            ),
            topo_ip_device_codes=device_codes,
            snapshot_version=snapshot_version,
        )

    if mode == "sequence":
        seq_path = _resolve_path(data.get("sequence_path", ""))
        target_file = _resolve_sequence_snapshot(
            seq_path, data.get("sequence_snapshot", "snapshot_000.json")
        )
        if not target_file.is_file():
            raise FileNotFoundError(f"Sequence snapshot file not found: {target_file}")
        raw = json.loads(target_file.read_text(encoding="utf-8"))
        return parse_package(raw)

    # mode == "real"
    alarm_path = _resolve_path(data.get("alarm_csv", DEFAULT_ALARM_CSV))
    if not alarm_path.is_file():
        raise FileNotFoundError(f"Alarm CSV export file not found: {alarm_path}")

    topo_path = _resolve_path(data.get("topo_ip", DEFAULT_TOPO_IP_CSV)) if data.get("with_topology") else None
    chain_ids = set(data["chain_ids"]) if data.get("chain_ids") else None
    limit = int(data["limit"]) if data.get("limit") else None
    bounded_subgraph = bool(data.get("bounded_subgraph", True))

    return build_real_replay_snapshot(
        alarm_csv_path=alarm_path,
        config=config,
        snapshot_id=snapshot_id,
        snapshot_version=snapshot_version,
        topo_ip_path=topo_path,
        chain_ids=chain_ids,
        limit=limit,
        bounded_subgraph=bounded_subgraph,
    )


def extract_package_summary(package: MockSnapshotPackage, chunk_target_bytes: int = 2 * 1024 * 1024) -> dict[str, Any]:
    chunk_target_bytes = _chunk_target_bytes(chunk_target_bytes)
    validation = validate_package(package)
    canonical_json = package_to_json(package, indent=None)
    raw_bytes = canonical_json.encode("utf-8")
    import hashlib
    sha256 = hashlib.sha256(raw_bytes).hexdigest()

    est_chunks = max(1, (len(raw_bytes) + chunk_target_bytes - 1) // chunk_target_bytes)

    sample_alarms = []
    for a in package.alarms[:15]:
        sample_alarms.append(
            {
                "alarm_id": a.alarm_id,
                "event_time": a.canonical_start_time or a.raw_start_time or "",
                "device_code": a.device_code or "",
                "alarm_name": a.alarm_name or "",
                "severity": a.severity_name or "INFO",
                "node_reference": a.node_reference or "",
                "quality_flags": [q.value if hasattr(q, "value") else str(q) for q in a.quality_flags],
            }
        )

    sample_chains = []
    for c in package.chains[:5]:
        sample_chains.append(
            {
                "chain_id": c.chain_id,
                "member_count": c.member_count,
                "chain_name": c.chain_name or "",
                "event_span_seconds": c.event_span_seconds,
                "source_kind": c.source_kind.value if hasattr(c.source_kind, "value") else str(c.source_kind),
            }
        )

    topo_nodes = len(package.topology.nodes) if package.topology else 0
    topo_edges = len(package.topology.edges) if package.topology else 0
    pair_count = (
        len(package.system_metadata.pair_metadata)
        if package.system_metadata and package.system_metadata.pair_metadata
        else 0
    )

    return {
        "snapshot_id": package.snapshot.snapshot_id,
        "snapshot_version": package.snapshot.snapshot_version,
        "source_kind": package.snapshot.source_kind.value if hasattr(package.snapshot.source_kind, "value") else str(package.snapshot.source_kind),
        "source": package.snapshot.source,
        "produced_at": package.snapshot.produced_at,
        "counts": {
            "alarms": len(package.alarms),
            "chains": len(package.chains),
            "topology_nodes": topo_nodes,
            "topology_edges": topo_edges,
            "pair_metadata": pair_count,
        },
        "size_bytes": len(raw_bytes),
        "estimated_chunks": est_chunks,
        "sha256_checksum": sha256,
        "contract_valid": validation.ok,
        "validation_errors": validation.errors,
        "sample_alarms": sample_alarms,
        "sample_chains": sample_chains,
    }


def _integer(value: str | None, default: int, *, minimum: int, maximum: int) -> int:
    try:
        result = int(value) if value is not None else default
    except ValueError:
        return default
    return min(max(result, minimum), maximum)


def dispatch_topology_route(
    path: str,
    query: dict[str, list[str]],
    *,
    source_root: str | Path | None = None,
) -> tuple[HTTPStatus, dict[str, Any]]:
    """Shared dispatch for read-only topology endpoints across HTTP handlers."""
    if path == "/api/topology/profiles":
        return HTTPStatus.OK, {"profiles": [profile.__dict__ for profile in dataset_profiles()]}

    if path not in {"/api/topology/projection", "/api/topology/search", "/api/topology/resolve"}:
        return HTTPStatus.NOT_FOUND, {"error": "endpoint not found"}

    profile = query.get("profile_id", [None])[0] or query.get("profile", [None])[0]
    if profile is None:
        return HTTPStatus.BAD_REQUEST, {"error": "profile_id is required"}

    try:
        if path == "/api/topology/projection":
            payload = projection_payload(
                profile,
                root_id=query.get("root_id", [None])[0],
                source_root=source_root,
                max_depth=_integer(query.get("depth", [None])[0], 3, minimum=0, maximum=8),
                max_children=_integer(query.get("child_limit", [None])[0], 50, minimum=1, maximum=200),
            )
            return HTTPStatus.OK, payload

        if path == "/api/topology/search":
            payload = search_payload(
                profile,
                query=query.get("q", [""])[0],
                source_root=source_root,
                limit=_integer(query.get("limit", [None])[0], 20, minimum=1, maximum=100),
            )
            return HTTPStatus.OK, payload

        if path == "/api/topology/resolve":
            identifier = query.get("identifier", [None])[0]
            if identifier is None:
                return HTTPStatus.BAD_REQUEST, {"error": "identifier is required"}
            payload = resolve_navigation_payload(
                profile,
                identifier,
                source_root=source_root,
            )
            return HTTPStatus.OK, payload

    except ValueError as exc:
        return HTTPStatus.BAD_REQUEST, {"error": str(exc)}

    return HTTPStatus.NOT_FOUND, {"error": "endpoint not found"}


class MockUIRequestHandler(SimpleHTTPRequestHandler):
    """Custom request handler for NocPro Mock UI and API."""

    def __init__(self, *args, default_kafka: str = "localhost:9092", **kwargs):
        self.default_kafka = default_kafka
        super().__init__(*args, **kwargs)

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _send_json(self, status: int, data: dict[str, Any]) -> None:
        raw = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            self.wfile.write(raw)
        except BrokenPipeError:
            return

    def _read_body_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError as exc:
            raise ValueError("Content-Length must be an integer") from exc
        if length <= 0:
            return {}
        if length > MAX_REQUEST_BODY_BYTES:
            raise ValueError(
                f"Request body exceeds {MAX_REQUEST_BODY_BYTES} byte Mock UI limit"
            )
        body = self.rfile.read(length).decode("utf-8")
        parsed = json.loads(body)
        if not isinstance(parsed, Mapping):
            raise ValueError("JSON request payload must be an object")
        return dict(parsed)

    def do_HEAD(self) -> None:
        path = self.path.split("?")[0]
        if path == "/" or path == "/index.html":
            index_file = ASSETS_DIR / "index.html"
            if not index_file.is_file():
                self.send_error(HTTPStatus.NOT_FOUND, "UI assets not found")
                return
            content = index_file.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            return
        super().do_HEAD()

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path == "/" or path == "/index.html":
            index_file = ASSETS_DIR / "index.html"
            if not index_file.is_file():
                self.send_error(HTTPStatus.NOT_FOUND, "UI assets not found")
                return
            content = index_file.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        if path == "/api/status":
            alarm_csv = _resolve_path(DEFAULT_ALARM_CSV)
            topo_csv = _resolve_path(DEFAULT_TOPO_IP_CSV)
            sequences = _discover_sequences()
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "service": "nocpro-mock",
                    "datasets": {
                        "alarm_csv": {
                            "path": str(alarm_csv),
                            "exists": alarm_csv.is_file(),
                            "size_bytes": alarm_csv.stat().st_size if alarm_csv.is_file() else 0,
                        },
                        "topo_ip": {
                            "path": str(topo_csv),
                            "exists": topo_csv.is_file(),
                            "size_bytes": topo_csv.stat().st_size if topo_csv.is_file() else 0,
                        },
                    },
                    "defaults": {
                        "kafka_bootstrap": getattr(self.server, "default_kafka", "localhost:9092"),
                        "kafka_topic": "nocpro.snapshot.v1",
                        "chunk_target_bytes": 2 * 1024 * 1024,
                        "snapshot_id": f"replay_{int(time.time())}",
                        "snapshot_version": "1",
                    },
                    "sequences": sequences,
                },
            )
            return

        if path.startswith("/api/topology/"):
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            status, payload = dispatch_topology_route(
                parsed.path,
                query,
                source_root=getattr(self.server, "source_root", None),
            )
            if status == HTTPStatus.NOT_FOUND:
                self.send_error(HTTPStatus.NOT_FOUND, f"Endpoint not found: {path}")
            else:
                self._send_json(status, payload)
            return

        self.send_error(HTTPStatus.NOT_FOUND, f"Endpoint not found: {path}")

    def do_POST(self) -> None:
        path = self.path.split("?")[0]
        try:
            body = self._read_body_json()
        except Exception as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": f"Invalid JSON payload: {exc}"})
            return

        if path == "/api/check-kafka":
            bootstrap = getattr(self.server, "default_kafka", "localhost:9092")
            requested = body.get("kafka_bootstrap")
            if requested not in (None, "", bootstrap):
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"ok": False, "error": "Kafka bootstrap is configured by the Mock server"},
                )
                return
            ok, msg = check_kafka_socket(bootstrap)
            self._send_json(HTTPStatus.OK, {"ok": ok, "message": msg, "bootstrap": bootstrap})
            return

        if path == "/api/preview":
            try:
                package = build_package_from_request(body)
                chunk_bytes = _chunk_target_bytes(
                    body.get("chunk_target_bytes", 2 * 1024 * 1024)
                )
                summary = extract_package_summary(package, chunk_target_bytes=chunk_bytes)
                self._send_json(HTTPStatus.OK, {"ok": True, "preview": summary})
            except Exception as exc:
                logger.exception("Failed to build preview snapshot: %s", exc)
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
            return

        if path == "/api/publish":
            start_t = time.perf_counter()
            bootstrap = getattr(self.server, "default_kafka", "localhost:9092")
            topic = DEFAULT_KAFKA_TOPIC
            requested_bootstrap = body.get("kafka_bootstrap")
            requested_topic = body.get("kafka_topic")
            if requested_bootstrap not in (None, "", bootstrap) or requested_topic not in (None, "", topic):
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"ok": False, "error": "Kafka destination is configured by the Mock server"},
                )
                return
            try:
                chunk_bytes = _chunk_target_bytes(
                    body.get("chunk_target_bytes", 2 * 1024 * 1024)
                )
                package = build_package_from_request(body)
                config = KafkaSnapshotConfig(
                    topic=topic,
                    chunk_target_bytes=chunk_bytes,
                )

                batch = asyncio.run(
                    publish_snapshot(
                        package,
                        bootstrap_servers=bootstrap,
                        config=config,
                    )
                )

                duration_ms = round((time.perf_counter() - start_t) * 1000, 2)
                events_log = []
                for c in batch.chunks:
                    events_log.append(
                        {
                            "event_type": c["event_type"],
                            "chunk_index": c["chunk_index"],
                            "chunk_count": c["chunk_count"],
                            "chunk_checksum": c["chunk_checksum"][:12] + "...",
                            "payload_size": len(c["payload"]),
                        }
                    )
                events_log.append(
                    {
                        "event_type": batch.complete["event_type"],
                        "expected_chunk_count": batch.complete["expected_chunk_count"],
                        "total_uncompressed_bytes": batch.complete["total_uncompressed_bytes"],
                        "snapshot_checksum": batch.complete["snapshot_checksum"][:12] + "...",
                    }
                )

                self._send_json(
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "snapshot_id": package.snapshot.snapshot_id,
                        "snapshot_version": package.snapshot.snapshot_version,
                        "topic": topic,
                        "bootstrap": bootstrap,
                        "chunks_published": len(batch.chunks),
                        "total_uncompressed_bytes": len(batch.canonical_bytes),
                        "compressed_bytes": len(batch.compressed_bytes),
                        "snapshot_checksum": batch.complete["snapshot_checksum"],
                        "duration_ms": duration_ms,
                        "events": events_log,
                    },
                )
            except ContractViolation as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"ok": False, "error": f"Contract validation failed: {exc}"},
                )
            except Exception as exc:
                logger.exception("Failed to publish to Kafka: %s", exc)
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "error": f"Kafka publish failed: {exc}"},
                )
            return

        self.send_error(HTTPStatus.NOT_FOUND, f"Endpoint not found: {path}")


def create_server(
    host: str = "0.0.0.0",
    port: int = 8085,
    default_kafka: str = "localhost:9092",
    *,
    source_root: str | Path | None = None,
) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), MockUIRequestHandler)
    server.default_kafka = default_kafka  # type: ignore[attr-defined]
    server.source_root = str(source_root) if source_root is not None else None  # type: ignore[attr-defined]
    return server


def run_server(
    host: str = "0.0.0.0",
    port: int = 8085,
    default_kafka: str = "localhost:9092",
    *,
    source_root: str | Path | None = None,
) -> None:
    server = create_server(host, port, default_kafka=default_kafka, source_root=source_root)
    url = f"http://{('127.0.0.1' if host == '0.0.0.0' else host)}:{port}"
    print(f"==================================================")
    print(f"🚀 NocPro Mock Web UI running at:")
    print(f"   👉 {url}")
    print(f"   Default Kafka bootstrap: {default_kafka}")
    print(f"   Press Ctrl+C to stop.")
    print(f"==================================================")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down NocPro Mock UI server...")
    finally:
        server.server_close()


def start_server_in_thread(
    host: str = "127.0.0.1",
    port: int = 0,
    default_kafka: str = "localhost:9092",
    *,
    source_root: str | Path | None = None,
) -> tuple[ThreadingHTTPServer, str]:
    """Start server in background thread, useful for tests."""
    server = create_server(host, port, default_kafka=default_kafka, source_root=source_root)
    actual_port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://{host}:{actual_port}"


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
        status, payload = dispatch_topology_route(
            parsed.path,
            parse_qs(parsed.query),
            source_root=getattr(self.server, "source_root", None),
        )
        self._json(status, payload)

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
