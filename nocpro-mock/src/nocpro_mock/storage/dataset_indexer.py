"""SQLite indexing and high-performance dataset caching for nocpro-mock.

Zero external dependencies: uses Python standard library sqlite3 + hashlib + json.
Provides atomic cache creation, cursor pagination, facet aggregation, and FTS5 search.
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import sqlite3
from typing import Any, Callable

from ..data_profiles import resolve_dataset_profile
from ..loaders.alarm_csv import AlarmCsvLoader
from ..loaders.topology_ip_csv import TopoIPLoader
from ..normalize.resource_mapping import ResourceMapper
from .active_alarm_fields import ACTIVE_ALARM_FIELDS, has_value, project_active_alarm

LOGGER = logging.getLogger(__name__)

MOCK_ROOT = Path(__file__).resolve().parents[3]
ENV_STATE_DIR = "NOCPRO_MOCK_STATE_DIR"
MAPPING_POLICY_VERSION = "v1-exact-only"
NORMALIZER_VERSION = "v1-canonical"
CONFIG_VERSION = "mock-v3-active-alarm-columns"
CURSOR_VERSION = "time-v1"


def get_state_dir() -> Path:
    """Return the state root directory, configurable via NOCPRO_MOCK_STATE_DIR."""
    custom = os.environ.get(ENV_STATE_DIR)
    if custom:
        root = Path(custom).resolve()
    else:
        root = MOCK_ROOT / ".cache"
    (root / "indexes").mkdir(parents=True, exist_ok=True)
    (root / "sequences").mkdir(parents=True, exist_ok=True)
    (root / "jobs").mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(parents=True, exist_ok=True)
    return root


def sha256_file(path: Path) -> str:
    """Stream a file in 1MB chunks to compute its full SHA-256 digest."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _topo_signature(path: Path | None) -> str:
    if path is None or not path.exists():
        return "NONE"
    if path.is_file():
        return sha256_file(path)
    if path.is_dir():
        items = []
        for child in sorted(path.rglob("*")):
            if child.is_file():
                items.append(f"{child.name}:{sha256_file(child)}")
        return hashlib.sha256(";".join(items).encode("utf-8")).hexdigest()
    return "NONE"


def compute_composite_fingerprint(
    profile_id: str,
    alarm_csv_path: Path,
    topo_path: Path | None = None,
    full_sha256: str | None = None,
) -> tuple[str, str, int, int]:
    """Compute composite dataset version and return (dataset_version, full_sha256, size, mtime_ns)."""
    stat = alarm_csv_path.stat()
    size_bytes = stat.st_size
    mtime_ns = stat.st_mtime_ns
    if full_sha256 is None:
        full_sha256 = sha256_file(alarm_csv_path)
    topo_sig = _topo_signature(topo_path)

    composite_raw = (
        f"{profile_id}:{full_sha256}:{topo_sig}:{MAPPING_POLICY_VERSION}:"
        f"{NORMALIZER_VERSION}:{CONFIG_VERSION}"
    )
    dataset_version = hashlib.sha256(composite_raw.encode("utf-8")).hexdigest()[:32]
    return dataset_version, full_sha256, size_bytes, mtime_ns


def _check_fts5(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_test USING fts5(text);")
        conn.execute("DROP TABLE IF EXISTS _fts5_test;")
        return True
    except sqlite3.OperationalError:
        return False


def encode_cursor(
    dataset_version: str,
    filter_hash: str,
    time_missing: int,
    canonical_start_time: str | None,
    logical_row: int,
) -> str:
    payload = {
        "cursor_version": CURSOR_VERSION,
        "dataset_version": dataset_version,
        "filter_hash": filter_hash,
        "time_missing": int(time_missing),
        "canonical_start_time": canonical_start_time,
        "logical_row": int(logical_row),
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(
    cursor_str: str, expected_version: str, expected_filter_hash: str
) -> dict[str, Any]:
    try:
        raw = base64.urlsafe_b64decode(cursor_str.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
        if payload.get("cursor_version") != CURSOR_VERSION:
            raise ValueError("Cursor version mismatch")
        if payload.get("dataset_version") != expected_version:
            raise ValueError(
                f"Cursor dataset_version mismatch: got {payload.get('dataset_version')}, expected {expected_version}"
            )
        if payload.get("filter_hash") != expected_filter_hash:
            raise ValueError("Cursor filter_hash mismatch: active query filters changed")
        time_missing = int(payload["time_missing"])
        if time_missing not in (0, 1):
            raise ValueError("time_missing must be 0 or 1")
        timestamp = payload.get("canonical_start_time")
        if time_missing == 0 and not timestamp:
            raise ValueError("non-null cursor requires canonical_start_time")
        if time_missing == 1 and timestamp is not None:
            raise ValueError("null-time cursor cannot include canonical_start_time")
        return {
            "time_missing": time_missing,
            "canonical_start_time": timestamp,
            "logical_row": int(payload["logical_row"]),
        }
    except (binascii.Error, TypeError, KeyError, ValueError) as exc:
        raise ValueError(f"Invalid cursor: {exc}") from exc


class DatasetIndexer:
    """Manages SQLite index creation, cursor-based pagination, and facet retrieval."""

    def __init__(self, state_dir: Path | None = None) -> None:
        self.state_dir = state_dir or get_state_dir()
        self.indexes_dir = self.state_dir / "indexes"
        self.indexes_dir.mkdir(parents=True, exist_ok=True)

    def get_db_path(self, profile_id: str, dataset_version: str) -> Path:
        return self.indexes_dir / f"{profile_id}_{dataset_version}.db"

    def is_indexed(
        self, profile_id: str, alarm_csv_path: Path, topo_path: Path | None = None
    ) -> tuple[bool, str]:
        """Check if a complete, valid SQLite database exists for the given file parameters."""
        if not alarm_csv_path.is_file():
            return False, ""
        stat = alarm_csv_path.stat()
        expected_topo_sig = _topo_signature(topo_path)
        # Fast scan candidate databases for this profile_id
        prefix = f"{profile_id}_"
        for db_file in self.indexes_dir.glob(f"{prefix}*.db"):
            version = db_file.stem[len(prefix):]
            try:
                with sqlite3.connect(f"file:{db_file}?mode=ro", uri=True) as conn:
                    row = conn.execute(
                        "SELECT size_bytes, mtime_ns, topo_signature FROM dataset_meta WHERE profile_id = ? AND dataset_version = ?",
                        (profile_id, version),
                    ).fetchone()
                    if (
                        row
                        and row[0] == stat.st_size
                        and row[1] == stat.st_mtime_ns
                        and row[2] == expected_topo_sig
                        and conn.execute(
                            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='dataset_field_profile'"
                        ).fetchone()
                    ):
                        return True, version
            except sqlite3.Error:
                continue
        return False, ""

    def count_alarms(self, profile_id: str, dataset_version: str) -> int:
        """Return total alarm count from index metadata or alarm table."""
        db_path = self.get_db_path(profile_id, dataset_version)
        if not db_path.is_file():
            return 0
        try:
            with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
                row = conn.execute(
                    "SELECT record_count FROM dataset_meta WHERE dataset_version = ?",
                    (dataset_version,),
                ).fetchone()
                if row and row[0] is not None:
                    return int(row[0])
                row = conn.execute("SELECT COUNT(*) FROM alarms").fetchone()
                return int(row[0]) if row and row[0] is not None else 0
        except sqlite3.Error:
            return 0

    def ensure_indexed(
        self,
        alarm_csv_path: Path,
        profile_id: str = "IP_NETWORK",
        topo_path: Path | None = None,
    ) -> tuple[str, Path]:
        """Ensure the dataset is indexed, building it if not already present."""
        indexed, version = self.is_indexed(profile_id, alarm_csv_path, topo_path)
        if indexed:
            return version, self.get_db_path(profile_id, version)
        return self.build_index(profile_id, alarm_csv_path, topo_path)

    def build_index(
        self,
        profile_id: str,
        alarm_csv_path: Path,
        topo_path: Path | None = None,
        progress_callback: Callable[[int, int | None], None] | None = None,
    ) -> tuple[str, Path]:
        """Build SQLite index atomically in *.db.tmp and replace upon completion."""
        if not alarm_csv_path.is_file():
            raise FileNotFoundError(f"Alarm CSV export file not found: {alarm_csv_path}")

        dataset_version, full_sha256, size_bytes, mtime_ns = compute_composite_fingerprint(
            profile_id, alarm_csv_path, topo_path
        )
        final_db = self.get_db_path(profile_id, dataset_version)
        if final_db.exists():
            return dataset_version, final_db

        tmp_db = self.indexes_dir / f"{profile_id}_{dataset_version}.db.tmp"
        if tmp_db.exists():
            tmp_db.unlink()

        conn = sqlite3.connect(tmp_db)
        try:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.execute("PRAGMA foreign_keys = ON;")

            has_fts = _check_fts5(conn)

            conn.executescript("""
                CREATE TABLE dataset_meta (
                    dataset_version TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    mtime_ns INTEGER NOT NULL,
                    topo_signature TEXT NOT NULL,
                    full_sha256 TEXT NOT NULL,
                    record_count INTEGER NOT NULL,
                    chain_count INTEGER NOT NULL,
                    earliest_time TEXT,
                    latest_time TEXT,
                    has_fts INTEGER NOT NULL,
                    indexed_at TEXT NOT NULL
                );

                CREATE TABLE alarms (
                    row_id TEXT PRIMARY KEY,
                    logical_row INTEGER NOT NULL,
                    alarm_id TEXT NOT NULL,
                    chaining_id TEXT,
                    alarm_name TEXT,
                    device_code TEXT,
                    node_reference TEXT,
                    severity TEXT,
                    canonical_start_time TEXT,
                    canonical_end_time TEXT,
                    mapping_status TEXT NOT NULL,
                    resource_id TEXT,
                    raw_json TEXT NOT NULL
                );

                CREATE TABLE alarm_quality_flags (
                    logical_row INTEGER NOT NULL,
                    quality_flag TEXT NOT NULL,
                    PRIMARY KEY (logical_row, quality_flag)
                );

                CREATE TABLE dataset_field_profile (
                    dataset_version TEXT NOT NULL,
                    field_key TEXT NOT NULL,
                    display_order INTEGER NOT NULL,
                    label TEXT NOT NULL,
                    field_group TEXT NOT NULL,
                    source_fields TEXT NOT NULL,
                    nonempty_count INTEGER NOT NULL,
                    row_count INTEGER NOT NULL,
                    coverage_ratio REAL NOT NULL,
                    active_consumer TEXT NOT NULL,
                    data_type TEXT NOT NULL,
                    required INTEGER NOT NULL,
                    PRIMARY KEY (dataset_version, field_key)
                );

                CREATE INDEX ix_alarms_logical_row ON alarms (logical_row);
                CREATE INDEX ix_alarms_chaining ON alarms (chaining_id);
                CREATE INDEX ix_alarms_device ON alarms (device_code);
                CREATE INDEX ix_alarms_name ON alarms (alarm_name);
                CREATE INDEX ix_alarms_severity ON alarms (severity);
                CREATE INDEX ix_alarms_start ON alarms (canonical_start_time);
                CREATE INDEX ix_alarms_chronological
                    ON alarms ((canonical_start_time IS NULL), canonical_start_time, logical_row);
                CREATE INDEX ix_alarms_mapping ON alarms (mapping_status);
                CREATE INDEX ix_quality_flag ON alarm_quality_flags (quality_flag, logical_row);
            """)

            if has_fts:
                conn.execute("""
                    CREATE VIRTUAL TABLE alarms_fts USING fts5(
                        alarm_id,
                        chaining_id,
                        alarm_name,
                        device_code,
                        node_reference,
                        content='alarms',
                        content_rowid='logical_row'
                    );
                """)

            # Build resource mapper according to profile capability invariants
            mapper: ResourceMapper | None = None
            if profile_id == "IP_NETWORK" and topo_path is not None and topo_path.is_file():
                loader = TopoIPLoader(topo_path)
                mapper = ResourceMapper(
                    loader.device_codes(),
                    topology_layer="IP",
                    source_version=sha256_file(topo_path),
                )

            csv_loader = AlarmCsvLoader(alarm_csv_path)
            batch_alarms = []
            batch_flags = []
            batch_fts = []

            record_count = 0
            chain_ids = set()
            earliest_time = None
            latest_time = None
            field_nonempty = {field.key: 0 for field in ACTIVE_ALARM_FIELDS}

            conn.execute("BEGIN TRANSACTION;")
            for record in csv_loader.iter_records():
                record_count += 1
                row_id = f"{dataset_version}:{record_count}"

                if record.chaining_id:
                    chain_ids.add(record.chaining_id)

                c_start = record.canonical_start_time.isoformat() if record.canonical_start_time else None
                c_end = record.canonical_end_time.isoformat() if record.canonical_end_time else None

                if c_start:
                    if earliest_time is None or c_start < earliest_time:
                        earliest_time = c_start
                    if latest_time is None or c_start > latest_time:
                        latest_time = c_start

                # Strict mapping invariant
                if profile_id == "IP_NETWORK" and mapper is not None:
                    res_id, status, _, _ = mapper.map_identifier(record.device_code)
                    if res_id is None and record.node_reference:
                        res_id, status, _, _ = mapper.map_identifier(record.node_reference)
                    mapping_status = status.value
                    resource_id = res_id
                else:
                    mapping_status = "UNAVAILABLE"
                    resource_id = None

                raw_json_str = json.dumps(record.raw, ensure_ascii=False)

                batch_alarms.append((
                    row_id,
                    record_count,
                    record.alarm_id,
                    record.chaining_id,
                    record.alarm_name or "",
                    record.device_code or "",
                    record.node_reference or "",
                    record.severity_name or "INFO",
                    c_start,
                    c_end,
                    mapping_status,
                    resource_id,
                    raw_json_str,
                ))

                flag_values = []
                for flag in record.quality_flags:
                    flag_val = flag.value if hasattr(flag, "value") else str(flag)
                    flag_values.append(flag_val)
                    batch_flags.append((record_count, flag_val))

                projected = project_active_alarm(
                    logical_row=record_count,
                    alarm_id=record.alarm_id,
                    chaining_id=record.chaining_id,
                    canonical_start_time=c_start,
                    canonical_end_time=c_end,
                    severity_name=record.severity_name or "INFO",
                    mapping_status=mapping_status,
                    resource_id=resource_id,
                    raw=record.raw,
                    quality_flags=flag_values,
                )
                for field in ACTIVE_ALARM_FIELDS:
                    if has_value(projected[field.key]):
                        field_nonempty[field.key] += 1

                if has_fts:
                    batch_fts.append((
                        record_count,
                        record.alarm_id,
                        record.chaining_id or "",
                        record.alarm_name or "",
                        record.device_code or "",
                        record.node_reference or "",
                    ))

                if len(batch_alarms) >= 5000:
                    conn.executemany(
                        "INSERT INTO alarms VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        batch_alarms,
                    )
                    if batch_flags:
                        conn.executemany(
                            "INSERT OR IGNORE INTO alarm_quality_flags VALUES (?, ?)",
                            batch_flags,
                        )
                    if has_fts:
                        conn.executemany(
                            "INSERT INTO alarms_fts (rowid, alarm_id, chaining_id, alarm_name, device_code, node_reference) VALUES (?, ?, ?, ?, ?, ?)",
                            batch_fts,
                        )
                    conn.commit()
                    conn.execute("BEGIN TRANSACTION;")
                    batch_alarms.clear()
                    batch_flags.clear()
                    batch_fts.clear()
                    if progress_callback:
                        progress_callback(record_count, None)

            if batch_alarms:
                conn.executemany(
                    "INSERT INTO alarms VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    batch_alarms,
                )
            if batch_flags:
                conn.executemany(
                    "INSERT OR IGNORE INTO alarm_quality_flags VALUES (?, ?)",
                    batch_flags,
                )
            if has_fts and batch_fts:
                conn.executemany(
                    "INSERT INTO alarms_fts (rowid, alarm_id, chaining_id, alarm_name, device_code, node_reference) VALUES (?, ?, ?, ?, ?, ?)",
                    batch_fts,
                )

            now_iso = datetime.now(timezone.utc).isoformat()
            topo_sig = _topo_signature(topo_path)
            conn.execute(
                "INSERT INTO dataset_meta VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    dataset_version,
                    profile_id,
                    str(alarm_csv_path.resolve()),
                    size_bytes,
                    mtime_ns,
                    topo_sig,
                    full_sha256,
                    record_count,
                    len(chain_ids),
                    earliest_time,
                    latest_time,
                    1 if has_fts else 0,
                    now_iso,
                ),
            )
            conn.executemany(
                """
                INSERT INTO dataset_field_profile VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        dataset_version,
                        field.key,
                        display_order,
                        field.label,
                        field.group,
                        json.dumps(field.source_fields),
                        field_nonempty[field.key],
                        record_count,
                        (field_nonempty[field.key] / record_count) if record_count else 0.0,
                        field.active_consumer,
                        field.data_type,
                        1 if field.required else 0,
                    )
                    for display_order, field in enumerate(ACTIVE_ALARM_FIELDS)
                ],
            )
            conn.commit()
        except Exception:
            conn.close()
            if tmp_db.exists():
                tmp_db.unlink()
            raise
        else:
            conn.close()
            # Atomic rename from tmp file
            os.replace(tmp_db, final_db)
            self._cleanup_old_indexes(profile_id, keep_version=dataset_version)
            return dataset_version, final_db

    def _cleanup_old_indexes(self, profile_id: str, keep_version: str) -> None:
        """Retain the current and one previous index for this profile to prevent disk bloat."""
        prefix = f"{profile_id}_"
        candidates = []
        for p in self.indexes_dir.glob(f"{prefix}*.db"):
            version = p.stem[len(prefix):]
            if version == keep_version:
                continue
            candidates.append((p.stat().st_mtime, p))
        candidates.sort(key=lambda item: item[0], reverse=True)
        # Keep at most 1 previous version
        for _, old_path in candidates[1:]:
            try:
                old_path.unlink(missing_ok=True)
                wal = old_path.with_suffix(".db-wal")
                shm = old_path.with_suffix(".db-shm")
                wal.unlink(missing_ok=True)
                shm.unlink(missing_ok=True)
            except OSError as exc:
                LOGGER.warning("Could not delete stale index %s: %s", old_path, exc)

    def get_active_columns(
        self, profile_id: str, dataset_version: str
    ) -> list[dict[str, Any]]:
        """Return required or populated active columns for this exact index."""
        db_path = self.get_db_path(profile_id, dataset_version)
        if not db_path.is_file():
            raise FileNotFoundError(f"Index database not found for version {dataset_version}")
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            rows = conn.execute(
                """
                SELECT field_key, label, field_group, source_fields,
                       nonempty_count, row_count, coverage_ratio,
                       active_consumer, data_type, required
                FROM dataset_field_profile
                WHERE dataset_version = ? AND (required = 1 OR nonempty_count > 0)
                ORDER BY display_order ASC
                """,
                (dataset_version,),
            ).fetchall()
        return [
            {
                "key": row[0],
                "label": row[1],
                "group": row[2],
                "source_fields": json.loads(row[3]),
                "nonempty_count": row[4],
                "row_count": row[5],
                "coverage_ratio": row[6],
                "active_consumer": row[7],
                "data_type": row[8],
                "required": bool(row[9]),
            }
            for row in rows
        ]

    def query_alarms(
        self,
        profile_id: str,
        dataset_version: str,
        *,
        severity: str | None = None,
        alarm_name: str | None = None,
        device_code: str | None = None,
        chaining_id: str | None = None,
        quality_flag: str | None = None,
        alarm_status: str | None = None,
        has_reason: bool = False,
        has_trouble_code: bool = False,
        has_parent: bool = False,
        mapping_status: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        query: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Execute server-side cursor pagination with exact filter composition."""
        limit = max(1, min(limit, 200))
        db_path = self.get_db_path(profile_id, dataset_version)
        if not db_path.is_file():
            raise FileNotFoundError(f"Index database not found for version {dataset_version}")

        filter_tokens = [
            f"sev={severity or ''}",
            f"name={alarm_name or ''}",
            f"dev={device_code or ''}",
            f"ch={chaining_id or ''}",
            f"qf={quality_flag or ''}",
            f"map={mapping_status or ''}",
            f"st={start_time or ''}",
            f"et={end_time or ''}",
            f"q={query or ''}",
            f"astat={alarm_status or ''}",
            f"hrea={1 if has_reason else 0}",
            f"htt={1 if has_trouble_code else 0}",
            f"hpar={1 if has_parent else 0}",
        ]
        filter_hash = hashlib.sha256(";".join(filter_tokens).encode("utf-8")).hexdigest()[:16]

        cursor_position = None
        if cursor:
            cursor_position = decode_cursor(cursor, dataset_version, filter_hash)

        where_clauses: list[str] = []
        params: dict[str, Any] = {"limit_plus_one": limit + 1}

        if severity:
            where_clauses.append("severity = :severity")
            params["severity"] = severity
        if alarm_name:
            where_clauses.append("alarm_name LIKE :alarm_name")
            params["alarm_name"] = f"%{alarm_name}%"
        if device_code:
            where_clauses.append("device_code LIKE :device_code")
            params["device_code"] = f"%{device_code}%"
        if chaining_id:
            where_clauses.append("chaining_id = :chaining_id")
            params["chaining_id"] = chaining_id
        if mapping_status:
            where_clauses.append("mapping_status = :mapping_status")
            params["mapping_status"] = mapping_status
        if start_time:
            where_clauses.append("canonical_start_time >= :start_time")
            params["start_time"] = start_time
        if end_time:
            where_clauses.append("canonical_start_time <= :end_time")
            params["end_time"] = end_time

        if alarm_status:
            where_clauses.append("json_extract(raw_json, '$.alarm_status') = :alarm_status")
            params["alarm_status"] = str(alarm_status)

        if has_reason:
            where_clauses.append(
                "json_extract(raw_json, '$.\"cah.reason\"') IS NOT NULL AND json_extract(raw_json, '$.\"cah.reason\"') != ''"
            )

        if has_trouble_code:
            where_clauses.append(
                "((json_extract(raw_json, '$.\"cah.trouble_code\"') IS NOT NULL AND json_extract(raw_json, '$.\"cah.trouble_code\"') != '') OR (json_extract(raw_json, '$.trouble_code') IS NOT NULL AND json_extract(raw_json, '$.trouble_code') != ''))"
            )

        if has_parent:
            where_clauses.append(
                "json_extract(raw_json, '$.parent_id') IS NOT NULL AND json_extract(raw_json, '$.parent_id') NOT IN ('[]', '', 'null')"
            )

        if quality_flag:
            if quality_flag.upper() == "CLEAN":
                where_clauses.append(
                    "logical_row NOT IN (SELECT logical_row FROM alarm_quality_flags)"
                )
            else:
                where_clauses.append(
                    "logical_row IN (SELECT logical_row FROM alarm_quality_flags WHERE quality_flag = :quality_flag)"
                )
                params["quality_flag"] = quality_flag


        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            conn.row_factory = sqlite3.Row

            has_fts = bool(
                conn.execute(
                    "SELECT has_fts FROM dataset_meta WHERE dataset_version = ?",
                    (dataset_version,),
                ).fetchone()[0]
            )

            if query and query.strip():
                clean_query = query.strip()
                if has_fts:
                    # Sanitize FTS query for double quotes
                    safe_query = '"' + clean_query.replace('"', '""') + '"*'
                    where_clauses.append(
                        "(logical_row IN (SELECT rowid FROM alarms_fts WHERE alarms_fts MATCH :fts_q) OR raw_json LIKE :like_q)"
                    )
                    params["fts_q"] = safe_query
                    params["like_q"] = f"%{clean_query}%"
                else:
                    where_clauses.append(
                        "(alarm_id LIKE :like_q OR alarm_name LIKE :like_q OR device_code LIKE :like_q OR chaining_id LIKE :like_q OR raw_json LIKE :like_q)"
                    )
                    params["like_q"] = f"%{clean_query}%"

            count_where_str = " AND ".join(where_clauses) if where_clauses else "1=1"
            total_filtered = conn.execute(
                f"SELECT COUNT(*) FROM alarms WHERE {count_where_str}", params
            ).fetchone()[0]

            if cursor_position:
                params["after_row"] = cursor_position["logical_row"]
                if cursor_position["time_missing"] == 0:
                    params["after_time"] = cursor_position["canonical_start_time"]
                    where_clauses.append(
                        "((canonical_start_time IS NOT NULL AND "
                        "(canonical_start_time > :after_time OR "
                        "(canonical_start_time = :after_time AND logical_row > :after_row))) "
                        "OR canonical_start_time IS NULL)"
                    )
                else:
                    where_clauses.append(
                        "canonical_start_time IS NULL AND logical_row > :after_row"
                    )

            where_str = " AND ".join(where_clauses) if where_clauses else "1=1"
            query_sql = f"""
                SELECT
                    row_id, logical_row, alarm_id, chaining_id, alarm_name,
                    device_code, node_reference, severity,
                    canonical_start_time, canonical_end_time,
                    mapping_status, resource_id, raw_json
                FROM alarms
                WHERE {where_str}
                ORDER BY
                    (canonical_start_time IS NULL) ASC,
                    canonical_start_time ASC,
                    logical_row ASC
                LIMIT :limit_plus_one
            """
            cursor_res = conn.execute(query_sql, params).fetchall()

            page_rows = [int(row["logical_row"]) for row in cursor_res[:limit]]
            flags_by_row: dict[int, list[str]] = {row: [] for row in page_rows}
            if page_rows:
                placeholders = ",".join("?" for _ in page_rows)
                for logical_row, flag in conn.execute(
                    f"SELECT logical_row, quality_flag FROM alarm_quality_flags "
                    f"WHERE logical_row IN ({placeholders}) ORDER BY logical_row, quality_flag",
                    page_rows,
                ):
                    flags_by_row[logical_row].append(flag)

        has_more = len(cursor_res) > limit
        items_slice = cursor_res[:limit]
        items = []
        last_position: tuple[int, str | None, int] | None = None

        for r in items_slice:
            raw_dict = {}
            if r["raw_json"]:
                try:
                    raw_dict = json.loads(r["raw_json"])
                except Exception:
                    pass

            projected = project_active_alarm(
                logical_row=r["logical_row"],
                alarm_id=r["alarm_id"],
                chaining_id=r["chaining_id"],
                canonical_start_time=r["canonical_start_time"],
                canonical_end_time=r["canonical_end_time"],
                severity_name=r["severity"],
                mapping_status=r["mapping_status"],
                resource_id=r["resource_id"],
                raw=raw_dict,
                quality_flags=flags_by_row.get(r["logical_row"], ()),
            )
            projected["row_id"] = r["row_id"]
            # Compatibility alias for existing API consumers; not an active UI column.
            projected["severity"] = projected["severity_name"]
            items.append(projected)
            last_position = (
                1 if r["canonical_start_time"] is None else 0,
                r["canonical_start_time"],
                r["logical_row"],
            )

        next_cursor = None
        if has_more and last_position:
            next_cursor = encode_cursor(
                dataset_version,
                filter_hash,
                last_position[0],
                last_position[1],
                last_position[2],
            )

        return {
            "items": items,
            "next_cursor": next_cursor,
            "has_more": has_more,
            "dataset_version": dataset_version,
            "total_filtered": total_filtered,
            "columns": self.get_active_columns(profile_id, dataset_version),
            "sort": {
                "field": "canonical_start_time",
                "direction": "ASC",
                "nulls": "LAST",
                "tie_breaker": "logical_row",
            },
        }

    def query_facets(self, profile_id: str, dataset_version: str) -> dict[str, Any]:
        """Aggregate fast faceted distributions for dashboard summary cards."""
        db_path = self.get_db_path(profile_id, dataset_version)
        if not db_path.is_file():
            raise FileNotFoundError(f"Index database not found for version {dataset_version}")

        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            meta = conn.execute(
                "SELECT record_count, chain_count, earliest_time, latest_time, indexed_at FROM dataset_meta WHERE dataset_version = ?",
                (dataset_version,),
            ).fetchone()
            if not meta:
                raise ValueError(f"Dataset meta not found for version {dataset_version}")

            severities = dict(
                conn.execute("SELECT severity, COUNT(*) FROM alarms GROUP BY severity ORDER BY COUNT(*) DESC").fetchall()
            )
            mappings = dict(
                conn.execute("SELECT mapping_status, COUNT(*) FROM alarms GROUP BY mapping_status ORDER BY COUNT(*) DESC").fetchall()
            )
            flags = dict(
                conn.execute("SELECT quality_flag, COUNT(*) FROM alarm_quality_flags GROUP BY quality_flag ORDER BY COUNT(*) DESC").fetchall()
            )
            top_alarm_names = [
                {"name": row[0], "count": row[1]}
                for row in conn.execute(
                    "SELECT alarm_name, COUNT(*) FROM alarms WHERE alarm_name != '' GROUP BY alarm_name ORDER BY COUNT(*) DESC LIMIT 10"
                ).fetchall()
            ]

        return {
            "record_count": meta[0],
            "chain_count": meta[1],
            "earliest_time": meta[2],
            "latest_time": meta[3],
            "indexed_at": meta[4],
            "severities": severities,
            "mapping_statuses": mappings,
            "quality_flags": flags,
            "top_alarm_names": top_alarm_names,
        }

    def get_alarm_detail(
        self, profile_id: str, dataset_version: str, row_id: str
    ) -> dict[str, Any]:
        """Retrieve 100% full raw JSON and canonical representation for the detail drawer."""
        db_path = self.get_db_path(profile_id, dataset_version)
        if not db_path.is_file():
            raise FileNotFoundError(f"Index database not found for version {dataset_version}")

        if ":" in str(row_id):
            parts = str(row_id).split(":", 1)
            if parts[0] != dataset_version:
                raise ValueError(
                    f"Dataset version mismatch: row_id version '{parts[0]}' does not match active version '{dataset_version}'"
                )
            logical_row = int(parts[1])
        elif str(row_id).isdigit():
            logical_row = int(row_id)
        else:
            raise ValueError(f"Invalid row_id format: {row_id}")

        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM alarms WHERE logical_row = ?", (logical_row,)
            ).fetchone()
            if not row:
                raise KeyError(f"Alarm row not found: {row_id}")

            flag_rows = conn.execute(
                "SELECT quality_flag FROM alarm_quality_flags WHERE logical_row = ?",
                (logical_row,),
            ).fetchall()
            flags = [f[0] for f in flag_rows]

        raw_dict = json.loads(row["raw_json"])
        canonical = {
            "row_id": row["row_id"],
            "logical_row": row["logical_row"],
            "alarm_id": row["alarm_id"],
            "chaining_id": row["chaining_id"],
            "chaining_name": raw_dict.get("chaining_name") or "",
            "alarm_name": row["alarm_name"],
            "content": raw_dict.get("content") or "",
            "addition_info": raw_dict.get("addition_info") or "",
            "device_code": row["device_code"],
            "device_name": raw_dict.get("device_name") or "",
            "device_ip": raw_dict.get("device_ip") or "",
            "device_type_name": raw_dict.get("device_type_name") or "",
            "vendor_name": raw_dict.get("vendor_name") or "",
            "network_type_name": raw_dict.get("network_type_name") or "",
            "network_class_name": raw_dict.get("network_class_name") or "",
            "component": raw_dict.get("component") or raw_dict.get("port") or "",
            "alarm_status": str(raw_dict.get("alarm_status") or "1"),
            "location_name": raw_dict.get("location_name") or "",
            "location_code": raw_dict.get("location_code") or "",
            "trouble_code": raw_dict.get("cah.trouble_code") or raw_dict.get("trouble_code") or "",
            "kedb_code": raw_dict.get("kedb_code") or "",
            "cah_reason": raw_dict.get("cah.reason") or "",
            "cah_comment": raw_dict.get("cah.comment") or "",
            "cah_resolve": raw_dict.get("cah.resolve") or "",
            "parent_id": raw_dict.get("parent_id") or "",
            "child_id": raw_dict.get("child_id") or "",
            "process_code": raw_dict.get("process_code") or "",
            "object_layer": raw_dict.get("object_layer") or "",
            "object_category": raw_dict.get("object_category") or "",
            "compute_host": raw_dict.get("compute_host") or "",
            "node_reference": row["node_reference"],
            "severity": row["severity"],
            "canonical_start_time": row["canonical_start_time"],
            "canonical_end_time": row["canonical_end_time"],
            "mapping_status": row["mapping_status"],
            "resource_id": row["resource_id"],
            "quality_flags": flags,
        }



        return {
            "canonical": canonical,
            "raw": raw_dict,
        }


_GLOBAL_INDEXER: DatasetIndexer | None = None


def get_dataset_indexer(state_dir: Path | None = None) -> DatasetIndexer:
    global _GLOBAL_INDEXER
    if _GLOBAL_INDEXER is None or (state_dir and state_dir != _GLOBAL_INDEXER.state_dir):
        _GLOBAL_INDEXER = DatasetIndexer(state_dir=state_dir)
    return _GLOBAL_INDEXER
