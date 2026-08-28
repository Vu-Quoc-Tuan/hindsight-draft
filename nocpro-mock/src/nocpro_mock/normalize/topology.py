"""topoIP relations -> canonical topology nodes and edges.

Every edge is ``IP_ADJACENCY`` with ``directed=False``. The source exposes no
routing direction, upstream/downstream, active path or dominator information, so
promoting these rows to ``LOGICAL_DEPENDENCY`` would be fabrication
(ADR-MOCK-0005, docs 06).

Freshness is computed from ``update_time_vipa``, but the PASS threshold comes
from versioned config; when it is unset the edge quality stays UNKNOWN (docs 06).
"""

from __future__ import annotations

from datetime import datetime

from ..contract import (
    ChainingUsage,
    ChainingUsageAssessment,
    ProvenanceClass,
    ProvenanceSubtype,
    QualityStatus,
    RelationType,
    SourceKind,
    TopologyEdge,
    TopologyNode,
)
from ..loaders.topology_ip_csv import TopoIPRelation

TOPOLOGY_LAYER_IP = "IP"


def _usage(source_id: str, source_version: str | None) -> ChainingUsageAssessment:
    """Whether NocPro chaining consumed this topology is not knowable from the export.

    Fail closed to UNKNOWN (ADR-0010): a complete executed rule/attribute set
    would be required to claim CONFIRMED_NOT_USED.
    """
    return ChainingUsageAssessment(
        source_id=source_id,
        source_version=source_version,
        chaining_config_version=None,
        usage=ChainingUsage.UNKNOWN.value,
        run_context=None,
    )


def freshness_quality(
    age_seconds: int | None, pass_max_age_seconds: int | None
) -> QualityStatus:
    """Resolve freshness quality; unknown inputs yield UNKNOWN, never PASS."""
    if age_seconds is None or pass_max_age_seconds is None:
        return QualityStatus.UNKNOWN
    return QualityStatus.PASS if age_seconds <= pass_max_age_seconds else QualityStatus.FAIL


def normalize_topo_ip(
    relations: list[TopoIPRelation],
    *,
    source_id: str,
    reference_time: datetime,
    source_version: str | None = None,
    freshness_pass_max_age_seconds: int | None = None,
) -> tuple[tuple[TopologyNode, ...], tuple[TopologyEdge, ...]]:
    """Convert adjacency rows into undirected contract edges plus their nodes."""
    node_classes: dict[str, str | None] = {}
    edges: list[TopologyEdge] = []
    seen_edge_ids: set[str] = set()

    for rel in relations:
        left, right = rel.device_code, rel.device_code_relation
        if not left or not right:
            # An adjacency needs both endpoints; a half row states nothing.
            continue

        node_classes.setdefault(left, rel.network_class_name)
        node_classes.setdefault(right, rel.network_class_name_relation)

        if left == right:
            # Self-adjacency carries no relational information.
            continue

        edge_id = f"topoip:{rel.relation_id}" if rel.relation_id else None
        if edge_id is None or edge_id in seen_edge_ids:
            # Endpoints are sorted so the identity of an undirected edge does not
            # depend on the exported column order.
            a, b = sorted((left, right))
            ports = sorted(
                filter(None, (rel.interface_port, rel.interface_port_relation))
            )
            edge_id = "topoip:" + ":".join([a, b, *ports])
            if edge_id in seen_edge_ids:
                continue
        seen_edge_ids.add(edge_id)

        age = rel.freshness_age_seconds(reference_time)
        edges.append(
            TopologyEdge(
                edge_id=edge_id,
                source_resource_id=left,
                target_resource_id=right,
                relation_type=RelationType.IP_ADJACENCY,
                directed=False,
                source_id=source_id,
                source_kind=SourceKind.REAL_EXPORT_REPLAY,
                source_version=source_version,
                freshness=(
                    rel.canonical_update_time.isoformat()
                    if rel.canonical_update_time
                    else None
                ),
                freshness_age_seconds=age,
                provenance_class=ProvenanceClass.EXTERNAL_OPERATIONAL,
                provenance_subtype=ProvenanceSubtype.TOPOLOGY_EXTERNAL,
                chaining_usage=_usage(source_id, source_version),
                quality_status=freshness_quality(age, freshness_pass_max_age_seconds),
            )
        )

    nodes = tuple(
        TopologyNode(
            resource_id=resource_id,
            source_id=source_id,
            source_kind=SourceKind.REAL_EXPORT_REPLAY,
            topology_layer=TOPOLOGY_LAYER_IP,
            network_class=network_class,
            source_version=source_version,
        )
        for resource_id, network_class in sorted(node_classes.items())
    )
    return nodes, tuple(edges)
