"""Normalize the topoIT archive into a directed *source-relation* graph.

The tables describe records and joins such as service-to-module and
module-to-database.  Their column direction is faithfully preserved for
navigation, but it does not establish operational dependency or propagation.
This module intentionally does not emit canonical ``TopologyEdge`` instances:
those can enable Explain topology semantics and currently have no safe relation
type for unverified source links.
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Literal, TypeAlias

from .alarm_csv import ENCODING, _configure_csv_limits

DirectionKind = Literal["SOURCE_RELATION"]
DependencySemantics = Literal["UNVERIFIED"]
RelationType: TypeAlias = Literal[
    "SERVICE_HAS_MODULE",
    "MODULE_HAS_INSTANCE",
    "MODULE_LINKS_DATABASE",
    "DATABASE_LINKS_SERVICE",
    "DATABASE_LINKS_INSTANCE",
    "INSTANCE_LINKS_STORAGE",
]


@dataclass(frozen=True)
class TopologyRelationNode:
    resource_id: str
    resource_type: Literal["SERVICE", "MODULE", "INSTANCE", "DATABASE", "STORAGE"]
    display_name: str
    source_tables: tuple[str, ...]


@dataclass(frozen=True)
class TopologyRelationEdge:
    source_id: str
    target_id: str
    relation_type: RelationType
    direction_kind: DirectionKind
    dependency_semantics: DependencySemantics
    source_table: str
    source_version: str


@dataclass(frozen=True)
class ITTopologyGraph:
    nodes: tuple[TopologyRelationNode, ...]
    edges: tuple[TopologyRelationEdge, ...]
    source_version: str
    source_tables: tuple[str, ...]


_TABLES = (
    "service_module_server.csv",
    "module_database.csv",
    "database.csv",
    "storage.csv",
)
_REQUIRED_COLUMNS: dict[str, frozenset[str]] = {
    "service_module_server.csv": frozenset({"service_id", "module_id", "instance_id"}),
    "module_database.csv": frozenset({"module_id", "database_id"}),
    "database.csv": frozenset({"database_id", "service_id", "instance_id"}),
    "storage.csv": frozenset({"storage_name", "instance_id"}),
}


def _value(row: dict[str, str], name: str) -> str | None:
    value = row.get(name, "").strip()
    return value or None


def _node_id(resource_type: str, raw_id: str) -> str:
    return f"it:{resource_type.lower()}:{raw_id}"


class ITTopologyLoader:
    """Streaming, schema-checked loader for the four topoIT relation tables."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        _configure_csv_limits()

    def load_graph(self) -> ITTopologyGraph:
        rows_by_table = {table: tuple(self._iter_rows(table)) for table in _TABLES}
        source_version = self._source_version()
        node_meta: dict[str, tuple[str, str, set[str]]] = {}
        edges: dict[tuple[str, str, str, str], TopologyRelationEdge] = {}

        def add_node(resource_type: Literal["SERVICE", "MODULE", "INSTANCE", "DATABASE", "STORAGE"], raw_id: str | None, display_name: str | None, table: str) -> str | None:
            if raw_id is None:
                return None
            resource_id = _node_id(resource_type, raw_id)
            name = display_name or raw_id
            existing = node_meta.get(resource_id)
            if existing is None:
                node_meta[resource_id] = (resource_type, name, {table})
            else:
                kind, existing_name, tables = existing
                tables.add(table)
                node_meta[resource_id] = (kind, existing_name, tables)
            return resource_id

        def add_edge(source: str | None, target: str | None, relation_type: RelationType, table: str) -> None:
            if source is None or target is None or source == target:
                return
            key = (source, target, relation_type, table)
            edges[key] = TopologyRelationEdge(source, target, relation_type, "SOURCE_RELATION", "UNVERIFIED", table, source_version)

        for row in rows_by_table["service_module_server.csv"]:
            service = add_node("SERVICE", _value(row, "service_id"), _value(row, "service_name"), "service_module_server.csv")
            module = add_node("MODULE", _value(row, "module_id"), _value(row, "module_name"), "service_module_server.csv")
            instance = add_node("INSTANCE", _value(row, "instance_id"), _value(row, "instance_ip"), "service_module_server.csv")
            add_edge(service, module, "SERVICE_HAS_MODULE", "service_module_server.csv")
            add_edge(module, instance, "MODULE_HAS_INSTANCE", "service_module_server.csv")
        for row in rows_by_table["module_database.csv"]:
            module = add_node("MODULE", _value(row, "module_id"), None, "module_database.csv")
            database = add_node("DATABASE", _value(row, "database_id"), None, "module_database.csv")
            add_edge(module, database, "MODULE_LINKS_DATABASE", "module_database.csv")
        for row in rows_by_table["database.csv"]:
            database = add_node("DATABASE", _value(row, "database_id"), _value(row, "database_name"), "database.csv")
            service = add_node("SERVICE", _value(row, "service_id"), _value(row, "service_name"), "database.csv")
            instance = add_node("INSTANCE", _value(row, "instance_id"), _value(row, "instance_ip"), "database.csv")
            add_edge(database, service, "DATABASE_LINKS_SERVICE", "database.csv")
            add_edge(database, instance, "DATABASE_LINKS_INSTANCE", "database.csv")
        for row in rows_by_table["storage.csv"]:
            instance = add_node("INSTANCE", _value(row, "instance_id"), _value(row, "instance_ip"), "storage.csv")
            storage = add_node("STORAGE", _value(row, "storage_name"), _value(row, "storage_name"), "storage.csv")
            add_edge(instance, storage, "INSTANCE_LINKS_STORAGE", "storage.csv")

        nodes = tuple(
            TopologyRelationNode(resource_id, resource_type, display_name, tuple(sorted(tables)))
            for resource_id, (resource_type, display_name, tables) in sorted(node_meta.items())
        )
        return ITTopologyGraph(nodes, tuple(edges.values()), source_version, _TABLES)

    def _iter_rows(self, table: str) -> Iterator[dict[str, str]]:
        path = self.directory / table
        if not path.is_file():
            raise ValueError(f"topoIT required source table missing: {path}")
        with path.open("r", newline="", encoding=ENCODING, errors="replace") as fh:
            reader = csv.DictReader(fh)
            columns = frozenset(reader.fieldnames or ())
            missing = sorted(_REQUIRED_COLUMNS[table] - columns)
            if missing:
                raise ValueError(f"topoIT {table} missing required columns: {', '.join(missing)}")
            for row in reader:
                yield {name: (value or "") for name, value in row.items() if name is not None}

    def _source_version(self) -> str:
        digest = hashlib.sha256()
        for table in _TABLES:
            path = self.directory / table
            if not path.is_file():
                raise ValueError(f"topoIT required source table missing: {path}")
            digest.update(table.encode("utf-8"))
            with path.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                    digest.update(chunk)
        return f"sha256:{digest.hexdigest()}"
