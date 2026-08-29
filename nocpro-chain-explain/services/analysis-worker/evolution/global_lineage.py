"""Persistable global episode-DAG identity across logical snapshots."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone

from libs.contracts import IngestedPackage

from .lineage import LineageConfig
from .pipeline import analyze_evolution


class OutOfOrderLineageError(ValueError):
    pass


@dataclass(frozen=True, order=True)
class LineageNodeKey:
    snapshot_id: str
    snapshot_chain_id: str


@dataclass(frozen=True)
class GlobalLineageNode:
    key: LineageNodeKey
    snapshot_time: str
    component_id: str
    branch_id: str


@dataclass(frozen=True)
class GlobalLineageEdge:
    parent: LineageNodeKey
    child: LineageNodeKey
    edge_type: str
    overlap_count: int
    contain_parent: float
    contain_child: float


@dataclass
class GlobalLineageComponent:
    component_id: str
    canonical_component_id: str
    first_snapshot_time: str
    last_snapshot_time: str
    status: str = "ACTIVE"


def deterministic_component_id(key: LineageNodeKey) -> str:
    raw = f"{key.snapshot_id}\0{key.snapshot_chain_id}".encode("utf-8")
    return f"lc_{hashlib.sha256(raw).hexdigest()[:24]}"


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass
class GlobalEpisodeDag:
    nodes: dict[LineageNodeKey, GlobalLineageNode] = field(default_factory=dict)
    edges: dict[tuple[LineageNodeKey, LineageNodeKey], GlobalLineageEdge] = field(
        default_factory=dict
    )
    components: dict[str, GlobalLineageComponent] = field(default_factory=dict)

    def canonical_component_id(self, component_id: str) -> str:
        seen: set[str] = set()
        current = component_id
        while True:
            if current in seen:
                raise ValueError("lineage component alias cycle")
            seen.add(current)
            component = self.components[current]
            if component.canonical_component_id == current:
                return current
            current = component.canonical_component_id

    def canonical_lineage(self, key: LineageNodeKey) -> str | None:
        node = self.nodes.get(key)
        if node is None:
            return None
        return self.canonical_component_id(node.component_id)

    def _new_component(self, key: LineageNodeKey, snapshot_time: str) -> str:
        component_id = deterministic_component_id(key)
        self.components.setdefault(
            component_id,
            GlobalLineageComponent(
                component_id=component_id,
                canonical_component_id=component_id,
                first_snapshot_time=snapshot_time,
                last_snapshot_time=snapshot_time,
            ),
        )
        return component_id

    def _merge_components(self, component_ids: set[str], snapshot_time: str) -> str:
        canonical_ids = {self.canonical_component_id(value) for value in component_ids}
        survivor = min(
            canonical_ids,
            key=lambda value: (
                _time(self.components[value].first_snapshot_time),
                value,
            ),
        )
        for component_id in canonical_ids - {survivor}:
            self.components[component_id].canonical_component_id = survivor
            self.components[component_id].status = "ALIASED"
        self.components[survivor].last_snapshot_time = snapshot_time
        return survivor

    def apply_snapshot(
        self,
        current: IngestedPackage,
        *,
        previous: IngestedPackage | None,
        config: LineageConfig,
    ) -> None:
        current_time = current.snapshot.snapshot_time
        current_keys = {
            chain_id: LineageNodeKey(current.snapshot.snapshot_id, chain_id)
            for chain_id in current.chains
        }
        if all(key in self.nodes for key in current_keys.values()):
            return
        if any(key in self.nodes for key in current_keys.values()):
            raise ValueError("partial replay of a lineage snapshot is not allowed")

        if self.nodes:
            latest = max(_time(node.snapshot_time) for node in self.nodes.values())
            if _time(current_time) <= latest:
                raise OutOfOrderLineageError(
                    "out-of-order lineage snapshot requires interval recompute"
                )

        if previous is None:
            for chain_id, key in sorted(current_keys.items()):
                component_id = self._new_component(key, current_time)
                self.nodes[key] = GlobalLineageNode(
                    key=key,
                    snapshot_time=current_time,
                    component_id=component_id,
                    branch_id=f"{component_id}:b0",
                )
            return

        evolution = analyze_evolution(previous, current, config=config)
        parents_by_child: dict[str, list] = {}
        for edge in evolution.edges:
            parents_by_child.setdefault(edge.child_chain_id, []).append(edge)

        event_by_child = {
            chain.snapshot_chain_id: chain.event.value
            for chain in evolution.chains
            if chain.snapshot_chain_id in current.chains
        }
        children_by_component: dict[str, list[str]] = {}
        component_for_child: dict[str, str] = {}
        for chain_id in sorted(current.chains):
            parent_components: set[str] = set()
            for edge in parents_by_child.get(chain_id, []):
                parent_key = LineageNodeKey(
                    previous.snapshot.snapshot_id, edge.parent_chain_id
                )
                parent_component = self.canonical_lineage(parent_key)
                if parent_component is None:
                    raise ValueError(f"parent lineage node missing: {parent_key}")
                parent_components.add(parent_component)
            key = current_keys[chain_id]
            component_id = (
                self._merge_components(parent_components, current_time)
                if parent_components
                else self._new_component(key, current_time)
            )
            component_for_child[chain_id] = component_id
            children_by_component.setdefault(component_id, []).append(chain_id)

        for component_id, chain_ids in children_by_component.items():
            for position, chain_id in enumerate(sorted(chain_ids)):
                key = current_keys[chain_id]
                self.nodes[key] = GlobalLineageNode(
                    key=key,
                    snapshot_time=current_time,
                    component_id=component_id,
                    branch_id=f"{component_id}:b{position}",
                )
                self.components[component_id].last_snapshot_time = current_time

        for edge in evolution.edges:
            parent = LineageNodeKey(
                previous.snapshot.snapshot_id, edge.parent_chain_id
            )
            child = current_keys[edge.child_chain_id]
            self.edges[(parent, child)] = GlobalLineageEdge(
                parent=parent,
                child=child,
                edge_type=event_by_child.get(edge.child_chain_id, "CONTINUE"),
                overlap_count=edge.shared,
                contain_parent=edge.contain_parent,
                contain_child=edge.contain_child,
            )
