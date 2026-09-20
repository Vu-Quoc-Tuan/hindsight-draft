"""HTTP Server and REST API for nocpro-mock Web UI.

Zero external dependencies: uses Python stdlib (http.server + asyncio).
"""

from __future__ import annotations

import functools
import json
import logging
import mimetypes
import queue
import socket
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse

from ..config import load_config
from ..data_profiles import dataset_profiles
from .topology_api import (
    projection_payload,
    resolve_navigation_payload,
    roots_payload,
    search_payload,
)
from ..contract import (
    ContractViolation,
    MockSnapshotPackage,
    package_to_json,
    parse_package,
    validate_package,
)
from ..fixtures.golden import load_golden_fixture
from ..jobs.job_manager import (
    ConflictError,
    JobStatus,
    get_job_manager,
)
from ..loaders.topology_ip_csv import TopoIPLoader
from ..producer.kafka_topology import (
    build_ip_topology_payload,
    build_it_topology_payload,
)
from ..replay.snapshot import build_golden_snapshot, build_real_replay_snapshot
from ..scenarios.sequence import load_sequence_manifest
from ..storage.dataset_indexer import (
    get_dataset_indexer,
    get_state_dir,
    _topo_signature,
)

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

DATASET_CATALOG: dict[str, dict[str, Any]] = {
    "alarm_ip": {
        "id": "alarm_ip",
        "name": "Alarm IP Network (212k alarms, Physical Topology)",
        "profile_id": "IP_NETWORK",
        "alarm_path": "datasets/raw/alarm/alarmIP.csv",
        "topo_path": "datasets/raw/topo/topoIP.csv",
        "description": "IP network alarms with physical adjacency topology correlation (topoIP.csv)",
    },
    "alarm_it": {
        "id": "alarm_it",
        "name": "Alarm IT Services (258k alarms, Multi-Tier Topology)",
        "profile_id": "IT_SERVICES",
        "alarm_path": "datasets/raw/alarm/alarmIT.csv",
        "topo_path": "datasets/raw/topo/topoIT",
        "description": "IT services alarms with multi-tier architecture topology (topoIT/)",
    },
    "alarm_data": {
        "id": "alarm_data",
        "name": "Alarm Legacy Export (8.7k alarms, Uncorrelated)",
        "profile_id": "ALARM_ONLY",
        "alarm_path": "datasets/raw/alarm/alarm_data.csv",
        "topo_path": None,
        "description": "Alarm export without topology correlation (mapping capability: UNAVAILABLE)",
    },
}


def _resolve_dataset_entry(dataset_id: str | None) -> dict[str, Any]:
    if not dataset_id or dataset_id not in DATASET_CATALOG:
        return DATASET_CATALOG["alarm_ip"]
    return DATASET_CATALOG[dataset_id]


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
        get_state_dir().resolve(),
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
    candidate_dirs = [
        _resolve_path(DEFAULT_SYNTHETIC_DIR),
        get_state_dir() / "sequences",
    ]
    seen_ids = set()
    sequences = []
    for syn_dir in candidate_dirs:
        if not syn_dir.is_dir():
            continue
        for item in sorted(syn_dir.iterdir()):
            if item.is_dir() and (item / "sequence.yaml").is_file():
                if item.name in seen_ids:
                    continue
                try:
                    manifest = load_sequence_manifest(item / "sequence.yaml")
                    seen_ids.add(item.name)
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

    if path not in {"/api/topology/projection", "/api/topology/search", "/api/topology/resolve", "/api/topology/roots"}:
        return HTTPStatus.NOT_FOUND, {"error": "endpoint not found"}

    profile = query.get("profile_id", [None])[0] or query.get("profile", [None])[0]
    if profile is None:
        return HTTPStatus.BAD_REQUEST, {"error": "profile_id is required"}

    try:
        if path == "/api/topology/roots":
            payload = roots_payload(
                profile,
                source_root=source_root,
                limit=_integer(query.get("limit", [None])[0], 10000, minimum=1, maximum=20000),
            )
            return HTTPStatus.OK, payload

        if path == "/api/topology/projection":
            payload = projection_payload(
                profile,
                root_id=query.get("root_id", [None])[0] or query.get("focal_resource_id", [None])[0] or query.get("focal_id", [None])[0],
                source_root=source_root,
                max_depth=_integer(query.get("depth", [None])[0], 3, minimum=0, maximum=8),
                max_children=_integer(query.get("child_limit", [None])[0], 10000, minimum=1, maximum=20000),
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


@functools.lru_cache(maxsize=4)
def _get_topo_ip_stats(path_str: str, mtime_ns: int) -> tuple[int, int, int, str, str]:
    path = Path(path_str)
    payload = build_ip_topology_payload(path)
    return (
        len(payload["nodes"]),
        len(payload["edges"]),
        len(payload.get("alias_resolution", [])),
        payload["source_version"],
        payload["topology_version"],
    )


@functools.lru_cache(maxsize=4)
def _get_topo_it_stats(dir_str: str, signature: str) -> tuple[int, int, int, str, str]:
    path = Path(dir_str)
    payload = build_it_topology_payload(path)
    return (
        len(payload["nodes"]),
        len(payload["edges"]),
        len(payload.get("alias_resolution", [])),
        payload["source_version"],
        payload["topology_version"],
    )


def _normalize_request_path(raw_path: str) -> str:
    path = raw_path.split("?")[0]
    if path.startswith("/mock-studio/"):
        return "/" + path[len("/mock-studio/") :]
    if path == "/mock-studio":
        return "/"
    return path


class MockUIRequestHandler(SimpleHTTPRequestHandler):
    """Custom request handler for NocPro Mock UI and API."""

    def __init__(self, *args, default_kafka: str = "localhost:9092", **kwargs):
        self.default_kafka = default_kafka
        super().__init__(*args, **kwargs)

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, PUT, DELETE")
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

    def _serve_static(self, path: str, head_only: bool = False) -> bool:
        if path in ("", "/", "/index.html"):
            target = ASSETS_DIR / "index.html"
        else:
            rel = path.lstrip("/")
            target = (ASSETS_DIR / rel).resolve()
            if not target.is_file() or not target.is_relative_to(ASSETS_DIR.resolve()):
                return False

        mime_type, _ = mimetypes.guess_type(str(target))
        if mime_type is None:
            if target.suffix == ".js":
                mime_type = "text/javascript; charset=utf-8"
            elif target.suffix == ".css":
                mime_type = "text/css; charset=utf-8"
            else:
                mime_type = "application/octet-stream"
        elif "text/" in mime_type or mime_type in ("application/javascript", "application/json"):
            mime_type += "; charset=utf-8"

        file_size = target.stat().st_size
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(file_size))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        if not head_only:
            try:
                self.wfile.write(target.read_bytes())
            except BrokenPipeError:
                pass
        return True

    def _handle_sse_stream(self, job_id: str) -> None:
        jm = get_job_manager()
        ctrl = jm.get_controller(job_id)
        if not ctrl:
            self.send_error(HTTPStatus.NOT_FOUND, f"Job '{job_id}' not found")
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        q = ctrl.subscribe()
        try:
            # First send current job snapshot as "event: init"
            initial_event = f"event: init\ndata: {json.dumps(ctrl.record.to_dict())}\n\n"
            self.wfile.write(initial_event.encode("utf-8"))
            self.wfile.flush()

            while True:
                try:
                    event = q.get(timeout=1.0)
                    if isinstance(event, dict):
                        ev_type = event.get("event_type", "message")
                        ev_payload = event.get("data", event)
                    else:
                        ev_type = getattr(event, "event_type", "message")
                        ev_payload = (
                            event.to_dict()
                            if hasattr(event, "to_dict")
                            else getattr(event, "data", str(event))
                        )
                    line = f"event: {ev_type}\ndata: {json.dumps(ev_payload)}\n\n"
                    self.wfile.write(line.encode("utf-8"))
                    self.wfile.flush()
                    if ev_type in ("complete", "error"):
                        break
                except queue.Empty:
                    # Heartbeat
                    if ctrl.record.status in (
                        JobStatus.COMPLETED,
                        JobStatus.FAILED,
                        JobStatus.STOPPED,
                        JobStatus.CANCELLED,
                    ):
                        break
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            ctrl.unsubscribe(q)

    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in ("/mock-studio", "/"):
            qs = f"?{parsed.query}" if parsed.query else ""
            self.send_response(HTTPStatus.MOVED_PERMANENTLY if parsed.path == "/mock-studio" else HTTPStatus.FOUND)
            self.send_header("Location", f"/mock-studio/{qs}")
            self.end_headers()
            return
        path = _normalize_request_path(self.path)
        if not path.startswith("/api/"):
            if self._serve_static(path, head_only=True):
                return
        self.send_error(HTTPStatus.NOT_FOUND, f"Endpoint not found: {path}")

    def do_GET(self) -> None:
        raw_path = self.path
        parsed = urlparse(raw_path)
        if parsed.path in ("/mock-studio", "/"):
            qs = f"?{parsed.query}" if parsed.query else ""
            self.send_response(HTTPStatus.MOVED_PERMANENTLY if parsed.path == "/mock-studio" else HTTPStatus.FOUND)
            self.send_header("Location", f"/mock-studio/{qs}")
            self.end_headers()
            return
        path = _normalize_request_path(raw_path)
        query = parse_qs(parsed.query)

        # 1. Static Assets
        if not path.startswith("/api/"):
            if self._serve_static(path):
                return
            self.send_error(HTTPStatus.NOT_FOUND, f"Endpoint not found: {path}")
            return

        # 2. Status
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

        # 3. Datasets Explorer Endpoints
        if path == "/api/datasets":
            indexer = get_dataset_indexer()
            datasets_list = []
            for ds_id, ds_info in DATASET_CATALOG.items():
                try:
                    alarm_csv = _resolve_path(ds_info["alarm_path"])
                    topo_path = _resolve_path(ds_info["topo_path"]) if ds_info["topo_path"] else None
                except Exception:
                    continue

                profile_id = ds_info["profile_id"]
                is_file = alarm_csv.is_file()
                size_bytes = alarm_csv.stat().st_size if is_file else 0
                is_indexed, fp = False, ""
                rec_count = 0
                if is_file:
                    is_indexed, fp = indexer.is_indexed(profile_id, alarm_csv, topo_path)
                    if is_indexed:
                        rec_count = indexer.count_alarms(profile_id, fp)

                datasets_list.append(
                    {
                        "id": ds_id,
                        "name": ds_info["name"],
                        "profile_id": profile_id,
                        "type": "ALARM_CSV",
                        "path": str(alarm_csv.relative_to(MOCK_ROOT) if alarm_csv.is_relative_to(MOCK_ROOT) else alarm_csv),
                        "topo_path": str(topo_path.relative_to(MOCK_ROOT) if topo_path and topo_path.is_relative_to(MOCK_ROOT) else (topo_path or "")),
                        "exists": is_file,
                        "size_bytes": size_bytes,
                        "indexed": is_indexed,
                        "fingerprint": fp,
                        "total_records": rec_count,
                        "description": ds_info["description"],
                    }
                )
            self._send_json(HTTPStatus.OK, {"ok": True, "datasets": datasets_list})
            return

        if path == "/api/alarms":
            dataset_id = query.get("dataset_id", ["alarm_ip"])[0]
            ds_entry = _resolve_dataset_entry(dataset_id)
            cursor = query.get("cursor", [None])[0]
            limit = _integer(query.get("limit", [None])[0], 50, minimum=1, maximum=200)
            severity = query.get("severity", [None])[0]
            quality_flag = query.get("quality_flag", [None])[0]
            device_code = query.get("device_code", [None])[0]
            alarm_name = query.get("alarm_name", [None])[0]
            chaining_id = query.get("chaining_id", [None])[0]
            search = query.get("search", [None])[0]
            mapping_status = query.get("mapping_status", [None])[0]
            start_time = query.get("start_time", [None])[0]
            end_time = query.get("end_time", [None])[0]
            alarm_status = query.get("alarm_status", [None])[0]
            has_reason = query.get("has_reason", ["0"])[0] in ("1", "true", "True")
            has_trouble_code = query.get("has_trouble_code", ["0"])[0] in ("1", "true", "True")
            has_parent = query.get("has_parent", ["0"])[0] in ("1", "true", "True")

            try:
                alarm_csv = _resolve_path(ds_entry["alarm_path"])
                topo_path = _resolve_path(ds_entry["topo_path"]) if ds_entry["topo_path"] else None
                profile_id = ds_entry["profile_id"]
                indexer = get_dataset_indexer()
                if not alarm_csv.is_file():
                    self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": f"Alarm CSV not found: {alarm_csv.name}"})
                    return

                dataset_version, _ = indexer.ensure_indexed(
                    alarm_csv,
                    profile_id=profile_id,
                    topo_path=topo_path,
                )

                page = indexer.query_alarms(
                    profile_id=profile_id,
                    dataset_version=dataset_version,
                    cursor=cursor,
                    limit=limit,
                    severity=severity,
                    quality_flag=quality_flag,
                    device_code=device_code,
                    alarm_name=alarm_name,
                    chaining_id=chaining_id,
                    alarm_status=alarm_status,
                    has_reason=has_reason,
                    has_trouble_code=has_trouble_code,
                    has_parent=has_parent,
                    mapping_status=mapping_status,
                    start_time=start_time,
                    end_time=end_time,
                    query=search,
                )
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "items": page["items"],
                        "next_cursor": page["next_cursor"],
                        "has_more": page["has_more"],
                        "total_estimate": page.get("total_filtered", 0),
                        "columns": page["columns"],
                        "sort": page["sort"],
                        "dataset_id": dataset_id,
                        "dataset_version": dataset_version,
                    },
                )
            except Exception as exc:
                logger.exception("Failed querying alarms: %s", exc)
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
            return

        if path == "/api/alarm-facets":
            dataset_id = query.get("dataset_id", ["alarm_ip"])[0]
            ds_entry = _resolve_dataset_entry(dataset_id)
            try:
                alarm_csv = _resolve_path(ds_entry["alarm_path"])
                topo_path = _resolve_path(ds_entry["topo_path"]) if ds_entry["topo_path"] else None
                profile_id = ds_entry["profile_id"]
                indexer = get_dataset_indexer()
                if not alarm_csv.is_file():
                    self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": f"Alarm CSV not found: {alarm_csv.name}"})
                    return

                dataset_version, _ = indexer.ensure_indexed(
                    alarm_csv,
                    profile_id=profile_id,
                    topo_path=topo_path,
                )

                facets = indexer.query_facets(profile_id, dataset_version)
                self._send_json(HTTPStatus.OK, {"ok": True, "facets": facets, "dataset_id": dataset_id, "dataset_version": dataset_version})
            except Exception as exc:
                logger.exception("Failed querying facets: %s", exc)
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
            return

        if path.startswith("/api/alarms/"):
            parts = path[len("/api/alarms/") :].split("/")
            if len(parts) == 2:
                dataset_id, row_id_str = parts
                ds_entry = _resolve_dataset_entry(dataset_id)
                try:
                    indexer = get_dataset_indexer()
                    alarm_csv = _resolve_path(ds_entry["alarm_path"])
                    topo_path = _resolve_path(ds_entry["topo_path"]) if ds_entry["topo_path"] else None
                    profile_id = ds_entry["profile_id"]
                    if not alarm_csv.is_file():
                        self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": f"Alarm CSV not found: {alarm_csv.name}"})
                        return

                    dataset_version, _ = indexer.ensure_indexed(
                        alarm_csv,
                        profile_id=profile_id,
                        topo_path=topo_path,
                    )

                    detail = indexer.get_alarm_detail(
                        profile_id=profile_id,
                        dataset_version=dataset_version,
                        row_id=row_id_str,
                    )
                    self._send_json(HTTPStatus.OK, {"ok": True, "detail": detail})
                except (KeyError, ValueError) as exc:
                    self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": f"Alarm '{row_id_str}' not found: {exc}"})
                except Exception as exc:
                    logger.exception("Failed getting alarm detail: %s", exc)
                    self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
                return

        # 4. Topology Metadata & Navigation Routes
        if path == "/api/topology/metadata":
            profile_id = query.get("profile_id", ["IP_NETWORK"])[0]
            try:
                if profile_id == "IP_NETWORK":
                    topo_csv = _resolve_path(DEFAULT_TOPO_IP_CSV)
                    node_count = 0
                    edge_count = 0
                    alias_count = 0
                    source_ver = "unknown"
                    canon_ver = "none"
                    if topo_csv.is_file():
                        node_count, edge_count, alias_count, source_ver, canon_ver = _get_topo_ip_stats(
                            str(topo_csv), topo_csv.stat().st_mtime_ns
                        )
                    meta = {
                        "profile_id": "IP_NETWORK",
                        "source_path": str(topo_csv.relative_to(MOCK_ROOT) if topo_csv.is_relative_to(MOCK_ROOT) else topo_csv),
                        "source_version": source_ver,
                        "canonical_version": canon_ver,
                        "stats": {
                            "node_count": node_count,
                            "edge_count": edge_count,
                            "alias_count": alias_count,
                        },
                        "capabilities": {
                            "relation_model": "PHYSICAL_ADJACENCY",
                            "direction_kind": "NONE",
                            "dependency_semantics": "UNAVAILABLE",
                            "navigation_eligible": True,
                            "p2_eligible": False,
                            "alarm_mapping": "PARTIAL_EXACT",
                        },
                        "status_notes": [
                            "Strict invariant: physical adjacency graph only.",
                            "P2 dependency semantics are UNAVAILABLE for IP adjacency.",
                            "Navigation hop distance eligible.",
                        ],
                    }
                elif profile_id == "IT_SERVICES":
                    topo_it = MOCK_ROOT / "datasets" / "raw" / "topo" / "topoIT"
                    node_count = 0
                    edge_count = 0
                    alias_count = 0
                    source_ver = "unknown"
                    canon_ver = "none"
                    if topo_it.is_dir():
                        sig = _topo_signature(topo_it)
                        node_count, edge_count, alias_count, source_ver, canon_ver = _get_topo_it_stats(
                            str(topo_it), sig
                        )
                    meta = {
                        "profile_id": "IT_SERVICES",
                        "source_path": str(topo_it.relative_to(MOCK_ROOT) if topo_it.is_relative_to(MOCK_ROOT) else topo_it),
                        "source_version": source_ver,
                        "canonical_version": canon_ver,
                        "stats": {
                            "node_count": node_count,
                            "edge_count": edge_count,
                            "alias_count": alias_count,
                        },
                        "capabilities": {
                            "relation_model": "SOURCE_RELATION",
                            "direction_kind": "SOURCE_RELATION",
                            "dependency_semantics": "UNVERIFIED",
                            "navigation_eligible": True,
                            "p2_eligible": False,
                            "alarm_mapping": "UNAVAILABLE",
                        },
                        "status_notes": [
                            "Strict invariant: source relation, unverified operational dependency.",
                            "Alarm resource mapping is UNAVAILABLE (fail-closed) until verified mapping exists.",
                        ],
                    }
                else:
                    meta = {
                        "profile_id": "ALARM_ONLY",
                        "capabilities": {
                            "relation_model": "NONE",
                            "direction_kind": "NONE",
                            "dependency_semantics": "NONE",
                            "navigation_eligible": False,
                            "p2_eligible": False,
                            "alarm_mapping": "NONE",
                        },
                        "status_notes": ["No topology reference attached to snapshots."],
                    }
                self._send_json(HTTPStatus.OK, {"ok": True, "metadata": meta})
            except Exception as exc:
                logger.exception("Failed getting topology metadata: %s", exc)
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
            return

        if path.startswith("/api/topology/"):
            status, payload = dispatch_topology_route(
                path,
                query,
                source_root=getattr(self.server, "source_root", None),
            )
            if status == HTTPStatus.NOT_FOUND:
                self.send_error(HTTPStatus.NOT_FOUND, f"Endpoint not found: {path}")
            else:
                self._send_json(status, payload)
            return

        # 5. Background Jobs API
        if path == "/api/jobs":
            jm = get_job_manager()
            limit = _integer(query.get("limit", [None])[0], 50, minimum=1, maximum=200)
            self._send_json(HTTPStatus.OK, {"ok": True, "jobs": jm.list_jobs(limit=limit)})
            return

        if path.startswith("/api/jobs/"):
            suffix = path[len("/api/jobs/") :]
            if suffix.endswith("/events"):
                job_id = suffix[: -len("/events")].strip("/")
                self._handle_sse_stream(job_id)
                return

            job_id = suffix.strip("/")
            jm = get_job_manager()
            job = jm.get_job(job_id)
            if not job:
                self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": f"Job '{job_id}' not found"})
                return
            self._send_json(HTTPStatus.OK, {"ok": True, "job": job.to_dict()})
            return

        self.send_error(HTTPStatus.NOT_FOUND, f"Endpoint not found: {path}")

    def do_POST(self) -> None:
        path = _normalize_request_path(self.path)

        # Cross-origin & CSRF check on mutating requests
        sec_fetch_site = self.headers.get("Sec-Fetch-Site")
        if sec_fetch_site == "cross-site":
            self._send_json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "Cross-origin requests to mutating endpoints are prohibited"})
            return

        origin = self.headers.get("Origin")
        if origin:
            parsed_origin = urlparse(origin)
            host = self.headers.get("Host", "").split(":")[0]
            if parsed_origin.hostname not in (host, "localhost", "127.0.0.1", "web", "gateway", "testserver"):
                self._send_json(HTTPStatus.FORBIDDEN, {"ok": False, "error": f"Untrusted origin: {origin}"})
                return

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
                jm = get_job_manager()
                record = jm.submit_single_publish_job(
                    package=package,
                    bootstrap_servers=bootstrap,
                    topic=topic,
                    chunk_target_bytes=chunk_bytes,
                )
                ctrl = jm.get_controller(record.job_id)
                if ctrl:
                    while ctrl.record.status in (JobStatus.PENDING, JobStatus.RUNNING):
                        time.sleep(0.05)
                    if ctrl.record.status == JobStatus.FAILED:
                        err_msg = ctrl.record.error or "Kafka publish failed"
                        self._send_json(
                            HTTPStatus.INTERNAL_SERVER_ERROR,
                            {"ok": False, "error": f"Kafka publish failed: {err_msg}"},
                        )
                        return
                    if ctrl.record.result:
                        res = dict(ctrl.record.result)
                        res["ok"] = True
                        res["duration_ms"] = round((time.perf_counter() - start_t) * 1000, 2)
                        self._send_json(HTTPStatus.OK, res)
                        return
                self._send_json(HTTPStatus.OK, {"ok": True, "job": record.to_dict()})
            except ConflictError as exc:
                self._send_json(HTTPStatus.CONFLICT, {"ok": False, "error": str(exc), "code": "LANE_CONFLICT"})
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

        if path == "/api/publish-sequence":
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
                seq_path = _resolve_path(body.get("sequence_path", ""))
                if not seq_path.is_dir():
                    self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": f"Sequence directory not found: {seq_path}"})
                    return

                chunk_bytes = _chunk_target_bytes(body.get("chunk_target_bytes", 2 * 1024 * 1024))
                delay_sec = max(0.0, float(body.get("delay_seconds", 0.3)))

                jm = get_job_manager()
                record = jm.submit_sequence_publish_job(
                    sequence_path=seq_path,
                    bootstrap_servers=bootstrap,
                    topic=topic,
                    chunk_target_bytes=chunk_bytes,
                    delay_seconds=delay_sec,
                    mode=body.get("mode", "paced"),
                )
                ctrl = jm.get_controller(record.job_id)
                if ctrl:
                    while ctrl.record.status in (JobStatus.PENDING, JobStatus.RUNNING, JobStatus.PAUSED, JobStatus.PAUSE_REQUESTED):
                        time.sleep(0.05)
                    if ctrl.record.status == JobStatus.FAILED:
                        err_msg = ctrl.record.error or "Kafka publish failed"
                        self._send_json(
                            HTTPStatus.INTERNAL_SERVER_ERROR,
                            {"ok": False, "error": f"Kafka publish failed: {err_msg}"},
                        )
                        return
                    if ctrl.record.result:
                        res = dict(ctrl.record.result)
                        res["ok"] = True
                        res["duration_ms"] = round((time.perf_counter() - start_t) * 1000, 2)
                        self._send_json(HTTPStatus.OK, res)
                        return
                self._send_json(HTTPStatus.OK, {"ok": True, "job": record.to_dict()})
            except ConflictError as exc:
                self._send_json(HTTPStatus.CONFLICT, {"ok": False, "error": str(exc), "code": "LANE_CONFLICT"})
            except Exception as exc:
                logger.exception("Failed to publish sequence to Kafka: %s", exc)
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": f"Kafka publish failed: {exc}"})
            return

        if path == "/api/slice-sequence":
            try:
                raw_scenario_id = str(body.get("scenario_id") or "real_alarm_evolution_v1").strip()
                import re
                if not re.match(r"^[a-zA-Z0-9_.-]+$", raw_scenario_id):
                    self._send_json(
                        HTTPStatus.BAD_REQUEST,
                        {"ok": False, "error": "scenario_id must contain only alphanumeric, dash, underscore, or period characters"},
                    )
                    return

                alarm_csv = body.get("alarm_csv", DEFAULT_ALARM_CSV)
                alarm_path = _resolve_path(alarm_csv)
                if not alarm_path.is_file():
                    self._send_json(
                        HTTPStatus.BAD_REQUEST,
                        {"ok": False, "error": f"Alarm CSV export file not found: {alarm_csv}"},
                    )
                    return

                num_snapshots = _integer(str(body.get("num_snapshots", 5)), 5, minimum=1, maximum=20)
                step_minutes = _integer(str(body.get("step_minutes", 5)), 5, minimum=1, maximum=120)
                window_minutes = _integer(str(body.get("window_minutes", 15)), 15, minimum=1, maximum=240)

                max_chains_raw = body.get("max_chains")
                max_chains = None
                if max_chains_raw not in (None, "", "null"):
                    max_chains = _integer(str(max_chains_raw), 50, minimum=1, maximum=10000)

                output_dir = get_state_dir() / "sequences" / raw_scenario_id
                profile_id = body.get("profile_id", "ALARM_ONLY")
                if profile_id not in ("ALARM_ONLY", "IP_NETWORK", "IT_SERVICES"):
                    self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": f"Invalid profile_id '{profile_id}' for slicing"})
                    return
                topo_path = _resolve_path(DEFAULT_TOPO_IP_CSV) if profile_id == "IP_NETWORK" else None
                topo_it_path = (MOCK_ROOT / "datasets" / "raw" / "topo" / "topoIT") if profile_id == "IT_SERVICES" else None

                jm = get_job_manager()
                record = jm.submit_slice_job(
                    alarm_csv_path=alarm_path,
                    output_dir=output_dir,
                    scenario_id=raw_scenario_id,
                    num_snapshots=num_snapshots,
                    step_minutes=step_minutes,
                    window_minutes=window_minutes,
                    max_chains=max_chains,
                    profile_id=profile_id,
                    topo_ip_path=topo_path,
                    topo_it_path=topo_it_path,
                )
                ctrl = jm.get_controller(record.job_id)
                if ctrl:
                    while ctrl.record.status in (JobStatus.PENDING, JobStatus.RUNNING, JobStatus.PAUSED, JobStatus.PAUSE_REQUESTED):
                        time.sleep(0.05)
                    if ctrl.record.status == JobStatus.FAILED:
                        self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": ctrl.record.error or "Slice failed"})
                        return
                    if ctrl.record.result:
                        res = {
                            "ok": True,
                            "summary": dict(ctrl.record.result),
                            "sequences": _discover_sequences(),
                        }
                        self._send_json(HTTPStatus.OK, res)
                        return

                sequences = _discover_sequences()
                self._send_json(HTTPStatus.OK, {"ok": True, "sequences": sequences})
            except ConflictError as exc:
                self._send_json(HTTPStatus.CONFLICT, {"ok": False, "error": str(exc), "code": "LANE_CONFLICT"})
            except Exception as exc:
                logger.exception("Failed to slice sequence: %s", exc)
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
            return

        # Background Jobs Endpoints
        if path == "/api/topology-publish-jobs":
            jm = get_job_manager()
            bootstrap = getattr(self.server, "default_kafka", "localhost:9092")
            profile_id = body.get("profile_id", "IP_NETWORK")
            source_path = _resolve_path(DEFAULT_TOPO_IP_CSV) if profile_id == "IP_NETWORK" else (MOCK_ROOT / "datasets" / "raw" / "topo" / "topoIT")
            try:
                record = jm.submit_topology_publish_job(
                    profile_id=profile_id,
                    source_path=source_path,
                    bootstrap_servers=bootstrap,
                    topic=body.get("topic", "nocpro.topology.v1"),
                    chunk_target_bytes=_chunk_target_bytes(body.get("chunk_target_bytes", 2 * 1024 * 1024)),
                )
                self._send_json(HTTPStatus.ACCEPTED, {"ok": True, "job": record.to_dict()})
            except ConflictError as exc:
                self._send_json(HTTPStatus.CONFLICT, {"ok": False, "error": str(exc), "code": "LANE_CONFLICT"})
            except Exception as exc:
                logger.exception("Failed submitting topology publish job: %s", exc)
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
            return

        if path == "/api/slice-jobs":
            jm = get_job_manager()
            try:
                raw_scenario_id = str(body.get("scenario_id") or "real_alarm_evolution_v1").strip()
                import re
                if not re.match(r"^[a-zA-Z0-9_.-]+$", raw_scenario_id):
                    self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "scenario_id must contain only alphanumeric, dash, underscore, or period characters"})
                    return
                alarm_csv = _resolve_path(body.get("alarm_csv", DEFAULT_ALARM_CSV))
                if not alarm_csv.is_file():
                    self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": f"Alarm CSV file not found: {alarm_csv}"})
                    return

                profile_id = body.get("profile_id", "ALARM_ONLY")
                if profile_id not in ("ALARM_ONLY", "IP_NETWORK", "IT_SERVICES"):
                    self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": f"Invalid profile_id '{profile_id}' for slicing"})
                    return
                topo_path = _resolve_path(DEFAULT_TOPO_IP_CSV) if profile_id == "IP_NETWORK" else None
                topo_it_path = (MOCK_ROOT / "datasets" / "raw" / "topo" / "topoIT") if profile_id == "IT_SERVICES" else None

                output_dir = get_state_dir() / "sequences" / raw_scenario_id
                record = jm.submit_slice_job(
                    alarm_csv_path=alarm_csv,
                    output_dir=output_dir,
                    scenario_id=raw_scenario_id,
                    num_snapshots=_integer(str(body.get("num_snapshots", 5)), 5, minimum=1, maximum=20),
                    step_minutes=_integer(str(body.get("step_minutes", 5)), 5, minimum=1, maximum=120),
                    window_minutes=_integer(str(body.get("window_minutes", 15)), 15, minimum=1, maximum=240),
                    max_chains=_integer(str(body["max_chains"]), 50, minimum=1, maximum=10000) if body.get("max_chains") else None,
                    profile_id=profile_id,
                    topo_ip_path=topo_path,
                    topo_it_path=topo_it_path,
                )
                self._send_json(HTTPStatus.ACCEPTED, {"ok": True, "job": record.to_dict()})
            except ConflictError as exc:
                self._send_json(HTTPStatus.CONFLICT, {"ok": False, "error": str(exc), "code": "LANE_CONFLICT"})
            except Exception as exc:
                logger.exception("Failed submitting slice job: %s", exc)
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
            return

        if path == "/api/publish-jobs":
            jm = get_job_manager()
            bootstrap = getattr(self.server, "default_kafka", "localhost:9092")
            try:
                job_type = body.get("type", "sequence")
                if job_type == "sequence":
                    seq_path = _resolve_path(body.get("sequence_path", ""))
                    if not seq_path.is_dir():
                        self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": f"Sequence directory not found: {seq_path}"})
                        return
                    record = jm.submit_sequence_publish_job(
                        sequence_path=seq_path,
                        bootstrap_servers=bootstrap,
                        topic=body.get("topic", DEFAULT_KAFKA_TOPIC),
                        chunk_target_bytes=_chunk_target_bytes(body.get("chunk_target_bytes", 2 * 1024 * 1024)),
                        delay_seconds=max(0.0, float(body.get("delay_seconds", 0.3))),
                        mode=body.get("mode", "paced"),
                    )
                else:
                    package = build_package_from_request(body)
                    record = jm.submit_single_publish_job(
                        package=package,
                        bootstrap_servers=bootstrap,
                        topic=body.get("topic", DEFAULT_KAFKA_TOPIC),
                        chunk_target_bytes=_chunk_target_bytes(body.get("chunk_target_bytes", 2 * 1024 * 1024)),
                    )
                self._send_json(HTTPStatus.ACCEPTED, {"ok": True, "job": record.to_dict()})
            except ConflictError as exc:
                self._send_json(HTTPStatus.CONFLICT, {"ok": False, "error": str(exc), "code": "LANE_CONFLICT"})
            except Exception as exc:
                logger.exception("Failed submitting publish job: %s", exc)
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
            return

        if path.startswith("/api/jobs/"):
            parts = path[len("/api/jobs/") :].split("/")
            if len(parts) == 2:
                job_id, action = parts
                jm = get_job_manager()
                ctrl = jm.get_controller(job_id)
                if not ctrl:
                    self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": f"Job '{job_id}' not found"})
                    return
                try:
                    if action == "pause":
                        ctrl.request_pause()
                    elif action == "resume":
                        ctrl.request_resume()
                    elif action == "stop":
                        ctrl.request_stop()
                    else:
                        self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": f"Unknown job action: {action}"})
                        return
                    self._send_json(HTTPStatus.OK, {"ok": True, "job": ctrl.record.to_dict()})
                except ValueError as exc:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
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
    print("==================================================")
    print("🚀 NocPro Mock Web UI running at:")
    print(f"   👉 {url}")
    print(f"   Default Kafka bootstrap: {default_kafka}")
    print("   Press Ctrl+C to stop.")
    print("==================================================")
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
