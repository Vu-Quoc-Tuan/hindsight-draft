"""Stable, read-only evidence records projected from compatible artifacts."""

from __future__ import annotations

import base64
import binascii
from dataclasses import asdict, is_dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Any

from libs.contracts.analysis_identity import AnalysisIdentity, analysis_identity_from_projection
from libs.contracts.topology_mapping import RESOLVED_STATUSES


_EVIDENCE_ID_PREFIX = "ev1_"
_MAX_EVIDENCE_PAGE_SIZE = 100
_MAX_EVIDENCE_PATH_HOPS = 4
_ALLOWED_KINDS = frozenset({"MAPPING", "TOPOLOGY_PATH", "AUDIT", "MEMBERSHIP", "REVIEW"})


class InvalidEvidenceCursor(ValueError):
    """The cursor is not a valid versioned evidence position."""


class StaleEvidenceCursor(ValueError):
    """The cursor belongs to a different identity or record set."""


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return _plain(value.value)
    if isinstance(value, AnalysisIdentity):
        return value.to_payload()
    if is_dataclass(value) and not isinstance(value, type):
        return _plain(asdict(value))
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            return _plain(dump(mode="json"))
        except TypeError:
            return _plain(dump())
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return None


def _canonical(value: Any) -> str:
    return json.dumps(
        _plain(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _identity(value: AnalysisIdentity | dict[str, Any]) -> AnalysisIdentity:
    if isinstance(value, AnalysisIdentity):
        return value
    adapted = analysis_identity_from_projection({"analysis_identity": value})
    if not adapted.available or adapted.identity is None:
        raise ValueError("IDENTITY_INCOMPLETE")
    return adapted.identity


def _mapping(value: Any) -> dict[str, Any] | None:
    value = _plain(value)
    return value if isinstance(value, dict) else None


def _non_negative_int(value: Any) -> bool:
    return type(value) is int and value >= 0


def _strings(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return sorted({item for item in value if isinstance(item, str) and item})


def _make_record(
    *,
    identity: AnalysisIdentity,
    kind: str,
    status: str,
    statement_kind: str,
    source_artifact_id: str | None,
    source_fingerprint: str | None,
    summary: str,
    reason_codes: list[str] | tuple[str, ...] = (),
    limitations: list[str] | tuple[str, ...] = (),
    path: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if kind not in _ALLOWED_KINDS:
        raise ValueError("unsupported evidence kind")
    semantic_payload = {
        "status": status,
        "statement_kind": statement_kind,
        "source_artifact_id": source_artifact_id,
        "summary": summary,
        "reason_codes": sorted(set(reason_codes)),
        "limitations": sorted(set(limitations)),
        "path": path,
    }
    digest = _sha256({
        "analysis_identity": identity.to_payload(),
        "kind": kind,
        "semantic_payload": semantic_payload,
        "source_fingerprint": source_fingerprint,
    })
    return {
        "evidence_id": f"{_EVIDENCE_ID_PREFIX}{digest}",
        "analysis_identity": identity.to_payload(),
        "kind": kind,
        "status": status,
        "statement_kind": statement_kind,
        "source_artifact_id": source_artifact_id,
        "source_fingerprint": source_fingerprint,
        "summary": summary,
        "reason_codes": sorted(set(reason_codes)),
        "limitations": sorted(set(limitations)),
        "path": path,
    }


def _topology_path_record(
    *, identity: AnalysisIdentity, topology: dict[str, Any], raw_path: Any
) -> dict[str, Any] | None:
    path_row = _mapping(raw_path)
    if path_row is None:
        return None
    nodes = path_row.get("path")
    source = path_row.get("source")
    target = path_row.get("target")
    hops = path_row.get("hop_count")
    max_hops = path_row.get("max_hops", _MAX_EVIDENCE_PATH_HOPS)
    relation = path_row.get("relation_type")
    declared_relations = _strings(path_row.get("relation_types"))
    raw_edge_relations = path_row.get("edge_relation_types")
    if isinstance(raw_edge_relations, list):
        edge_relation_types = list(raw_edge_relations)
    elif isinstance(relation, str) and relation and relation != "MIXED":
        edge_relation_types = [relation] * hops if _non_negative_int(hops) else []
    else:
        edge_relation_types = []
    if not declared_relations and isinstance(relation, str) and relation and relation != "MIXED":
        declared_relations = [relation]
    raw_edge_provenance = path_row.get("edge_provenance")
    edge_provenance_present = "edge_provenance" in path_row
    edge_provenance = raw_edge_provenance if isinstance(raw_edge_provenance, list) else []
    semantic = path_row.get("traversal_semantic")
    statuses = _strings(path_row.get("mapping_statuses"))
    edge_provenance_valid = not edge_provenance_present or (
        isinstance(raw_edge_provenance, list)
        and isinstance(nodes, list)
        and _non_negative_int(hops)
        and len(nodes) == hops + 1
        and len(raw_edge_provenance) == hops
        and all(
            isinstance(edge, dict)
            and type(edge.get("hop_index")) is int
            and edge.get("hop_index") == index
            and edge.get("from_resource_id") == nodes[index]
            and edge.get("to_resource_id") == nodes[index + 1]
            and isinstance(edge.get("relation_types"), list)
            and bool(edge.get("relation_types"))
            and all(
                isinstance(relation_type, str) and relation_type
                for relation_type in edge.get("relation_types", [])
            )
            and bool(_strings(edge.get("relation_types")))
            and isinstance(edge.get("source_records"), list)
            and bool(edge.get("source_records"))
            and all(
                isinstance(source_record, dict)
                and source_record.get("relation_type") in _strings(edge.get("relation_types"))
                for source_record in edge.get("source_records", [])
            )
            for index, edge in enumerate(raw_edge_provenance)
        )
    )
    edge_relations_well_formed = (
        _non_negative_int(hops)
        and len(edge_relation_types) == hops
        and all(isinstance(item, str) and item for item in edge_relation_types)
    )
    edge_relations_supported = (
        edge_relations_well_formed
        and bool(declared_relations)
        and set(edge_relation_types).issubset(set(declared_relations))
    )
    malformed = (
        not isinstance(nodes, list)
        or len(nodes) < 2
        or not all(isinstance(node, str) and node for node in nodes)
        or len(set(nodes)) != len(nodes)
        or not isinstance(source, str)
        or not isinstance(target, str)
        or nodes[0] != source
        or nodes[-1] != target
        or not _non_negative_int(hops)
        or hops != len(nodes) - 1
        or not _non_negative_int(max_hops)
        or max_hops == 0
        or hops > max_hops
        or not isinstance(relation, str)
        or not relation
        or not edge_relations_supported
        or not edge_provenance_valid
        or semantic != "UNDIRECTED_STRUCTURAL_CONNECTIVITY"
    )
    mapping_unverified = not statuses or not set(statuses).issubset(RESOLVED_STATUSES)
    source_partial = str(topology.get("status") or "").upper() != "AVAILABLE"
    analysis_truncated = topology.get("analysis_truncated") is True
    reasons: list[str] = []
    status = "AVAILABLE"
    path_value: dict[str, Any] | None = None
    if malformed:
        status = "UNAVAILABLE"
        reasons.append("TOPOLOGY_PATH_INVALID")
    elif mapping_unverified:
        status = "UNAVAILABLE"
        reasons.append("TOPOLOGY_MAPPING_NOT_VERIFIED")
    else:
        path_value = {
            "resource_ids": list(nodes),
            "relation_types": edge_relation_types,
            "hop_count": hops,
            "traversal_semantic": semantic,
            "max_hops": max_hops,
            "topology_version": identity.topology_version or "",
            "mapping_statuses": statuses,
            "analysis_truncated": analysis_truncated,
            "edge_provenance": edge_provenance,
        }
        if source_partial:
            reasons.append("TOPOLOGY_SOURCE_PARTIAL")
        if analysis_truncated:
            reasons.append("TOPOLOGY_ANALYSIS_TRUNCATED")
    summary = (
        f"{source} ↔ {target}: {hops} hop trong giới hạn {max_hops} hop; "
        "đây là kết nối cấu trúc không xác nhận quan hệ phụ thuộc hay nguyên nhân."
        if path_value is not None
        else "Không thể xác minh đường topology từ projection hiện có."
    )
    limitations = [
        "UNDIRECTED_STRUCTURAL_CONNECTIVITY_IS_NOT_CAUSAL_DEPENDENCY",
        "A_BOUNDED_PATH_DOES_NOT_PROVE_GLOBAL_DISCONNECTION",
    ]
    if source_partial:
        limitations.append("TOPOLOGY_SOURCE_IS_PARTIAL")
    return _make_record(
        identity=identity,
        kind="TOPOLOGY_PATH",
        status=status,
        statement_kind="DERIVED",
        source_artifact_id=None,
        source_fingerprint=identity.input_fingerprint,
        summary=summary,
        reason_codes=reasons,
        limitations=limitations,
        path=path_value,
    )


def _pair_path_records(
    *, identity: AnalysisIdentity, pair_evidence: Any
) -> list[dict[str, Any]]:
    if not isinstance(pair_evidence, (list, tuple)):
        return []
    records: list[dict[str, Any]] = []
    for pair in pair_evidence[:100]:
        pair_row = _mapping(pair)
        if pair_row is None:
            continue
        alarm_a = pair_row.get("alarm_id_a")
        alarm_b = pair_row.get("alarm_id_b")
        for item in pair_row.get("evidence") or ():
            evidence = _mapping(item)
            if evidence is None or evidence.get("channel_family") != "Dep_hop":
                continue
            state = str(evidence.get("state") or "").upper()
            metadata = _mapping(evidence.get("evidence_metadata")) or {}
            raw_path = _mapping(metadata.get("topology_path"))
            source_id = evidence.get("source_id")
            source_version = evidence.get("source_version")
            source_signature = {
                "source_ref": evidence.get("source_ref"),
                "source_id": source_id,
                "source_version": source_version,
                "generator_version": evidence.get("generator_version"),
            }
            source_fingerprint = _sha256(source_signature)
            pair_label = f"{alarm_a or '?'} ↔ {alarm_b or '?'}"
            if state == "UNAVAILABLE" or raw_path is None:
                records.append(_make_record(
                    identity=identity,
                    kind="TOPOLOGY_PATH",
                    status="UNAVAILABLE",
                    statement_kind="DERIVED",
                    source_artifact_id=str(source_id) if source_id is not None else None,
                    source_fingerprint=source_fingerprint,
                    summary=(
                        f"Pair WHY {pair_label}: Dep_hop chưa có đường topology khả dụng."
                    ),
                    reason_codes=["PAIR_TOPOLOGY_PATH_UNAVAILABLE"],
                    limitations=[
                        "PAIR_DEP_HOP_USES_ITS_OWN_RELATION_AND_HOP_POLICY",
                        "NO_PATH_WITHIN_BOUND_DOES_NOT_PROVE_GLOBAL_DISCONNECTION",
                    ],
                ))
                continue
            nodes = raw_path.get("nodes")
            hops = raw_path.get("hop_count")
            max_hops = raw_path.get("max_hops")
            raw_relations = raw_path.get("relation_types")
            relation_types = _strings(raw_relations)
            raw_edge_relations = raw_path.get("edge_relation_types")
            edge_relation_types = (
                list(raw_edge_relations)
                if isinstance(raw_edge_relations, list)
                and all(isinstance(relation, str) and relation for relation in raw_edge_relations)
                else []
            )
            traversal = raw_path.get("traversal_semantic")
            mapping_statuses = _strings(raw_path.get("mapping_statuses"))
            valid = (
                isinstance(nodes, list)
                and len(nodes) >= 2
                and all(isinstance(node, str) and node for node in nodes)
                and len(set(nodes)) == len(nodes)
                and _non_negative_int(hops)
                and hops == len(nodes) - 1
                and _non_negative_int(max_hops)
                and max_hops > 0
                and hops <= max_hops
                and len(edge_relation_types) == hops
                and len(set(edge_relation_types)) == 1
                and bool(relation_types)
                and set(edge_relation_types).issubset(set(relation_types))
                and traversal == "STRUCTURAL_TOPOLOGY_PATH_NOT_CAUSAL"
                and mapping_statuses
                and set(mapping_statuses).issubset(RESOLVED_STATUSES)
            )
            path_value = None
            reasons: list[str] = []
            status_value = "AVAILABLE" if valid else "UNAVAILABLE"
            if valid:
                path_value = {
                    "resource_ids": list(nodes),
                    "relation_types": edge_relation_types,
                    "hop_count": hops,
                    "traversal_semantic": traversal,
                    "max_hops": max_hops,
                    "topology_version": identity.topology_version or "",
                    "mapping_statuses": mapping_statuses,
                    "analysis_truncated": False,
                    "direction_policy": str(raw_path.get("direction_policy") or ""),
                }
            else:
                reasons.append("PAIR_TOPOLOGY_PATH_INCOMPLETE")
            summary = (
                f"Pair WHY {pair_label}: {hops} hop trong giới hạn {max_hops} hop; "
                "quan hệ cấu trúc, không xác nhận chiều nhân quả."
                if valid
                else f"Pair WHY {pair_label}: chưa đủ metadata để xác minh đường topology."
            )
            records.append(_make_record(
                identity=identity,
                kind="TOPOLOGY_PATH",
                status=status_value,
                statement_kind="DERIVED",
                source_artifact_id=str(source_id) if source_id is not None else None,
                source_fingerprint=source_fingerprint,
                summary=summary,
                reason_codes=reasons,
                limitations=[
                    "PAIR_DEP_HOP_USES_ITS_OWN_RELATION_AND_HOP_POLICY",
                    "STRUCTURAL_PATH_IS_NOT_CAUSAL_DIRECTION",
                ],
                path=path_value,
            ))
    return records


def build_evidence_records(
    *,
    identity: AnalysisIdentity | dict[str, Any],
    overview_projection: dict[str, Any] | None,
    pair_evidence: Any,
    audit_artifact: Any,
    review_result: Any,
) -> list[dict[str, Any]]:
    """Build bounded typed evidence from already-available inputs only.

    The builder performs no persistence access, path search, analysis, or
    provider call. Missing inputs become explicit non-available records.
    """
    resolved_identity = _identity(identity)
    projection = _mapping(overview_projection) or {}
    topology = _mapping(projection.get("topology")) or {}
    assessment = _mapping(projection.get("quality_assessment")) or {}
    coverage = _mapping(assessment.get("evidence_coverage")) or {}
    source_fingerprint = resolved_identity.input_fingerprint
    records: list[dict[str, Any]] = []

    mapped = topology.get("mapped_alarm_count", topology.get("mapped"))
    total = topology.get("total")
    if _non_negative_int(mapped) and _non_negative_int(total) and mapped <= total:
        mapping_reasons = [] if mapped == total else ["TOPOLOGY_MAPPING_INCOMPLETE"]
        mapping_status = "AVAILABLE"
        mapping_summary = f"Đã ánh xạ {mapped}/{total} cảnh báo vào tài nguyên topology."
    else:
        mapping_reasons = ["TOPOLOGY_MAPPING_UNAVAILABLE"]
        mapping_status = "UNAVAILABLE"
        mapping_summary = "Chưa có số liệu mapping topology hợp lệ cho chain này."
    records.append(_make_record(
        identity=resolved_identity,
        kind="MAPPING",
        status=mapping_status,
        statement_kind="OBSERVED",
        source_artifact_id=None,
        source_fingerprint=source_fingerprint,
        summary=mapping_summary,
        reason_codes=mapping_reasons,
        limitations=["MAPPING_DOES_NOT_ESTABLISH_DEPENDENCY"],
    ))

    membership = _mapping(coverage.get("membership"))
    evaluated = membership.get("evaluated") if membership else None
    member_total = membership.get("total") if membership else None
    if (
        _non_negative_int(evaluated)
        and _non_negative_int(member_total)
        and evaluated <= member_total
        and member_total > 0
    ):
        membership_status = "AVAILABLE"
        membership_reasons = (
            [] if evaluated == member_total else ["MEMBERSHIP_COVERAGE_INCOMPLETE"]
        )
        membership_summary = f"Đánh giá vai trò {evaluated}/{member_total} cảnh báo."
    else:
        membership_status = "UNAVAILABLE"
        membership_reasons = ["MEMBERSHIP_EVIDENCE_UNAVAILABLE"]
        membership_summary = "Chưa có số liệu đánh giá vai trò thành viên hợp lệ."
    records.append(_make_record(
        identity=resolved_identity,
        kind="MEMBERSHIP",
        status=membership_status,
        statement_kind="DERIVED",
        source_artifact_id=None,
        source_fingerprint=source_fingerprint,
        summary=membership_summary,
        reason_codes=membership_reasons,
        limitations=["MEMBERSHIP_ROLE_IS_NOT_ROOT_CAUSE"],
    ))

    display_paths = topology.get("display_paths")
    if isinstance(display_paths, list):
        path_records = [
            record
            for path in display_paths[:100]
            if (record := _topology_path_record(
                identity=resolved_identity, topology=topology, raw_path=path
            )) is not None
        ]
        records.extend(path_records)
        if not path_records:
            records.append(_make_record(
                identity=resolved_identity,
                kind="TOPOLOGY_PATH",
                status="UNAVAILABLE",
                statement_kind="DERIVED",
                source_artifact_id=None,
                source_fingerprint=source_fingerprint,
                summary=(
                    "Không ghi nhận witness trong giới hạn topology hiện dùng; "
                    "điều này không chứng minh không có đường ngoài giới hạn."
                ),
                reason_codes=["NO_PATH_WITHIN_DECLARED_BOUND"],
                limitations=["BOUNDED_SEARCH_DOES_NOT_PROVE_GLOBAL_DISCONNECTION"],
            ))
    else:
        records.append(_make_record(
            identity=resolved_identity,
            kind="TOPOLOGY_PATH",
            status="UNAVAILABLE",
            statement_kind="DERIVED",
            source_artifact_id=None,
            source_fingerprint=source_fingerprint,
            summary="Chưa có path projection phù hợp với topology identity hiện tại.",
            reason_codes=["TOPOLOGY_PATH_NOT_EVALUATED"],
            limitations=["NO_PATH_WITNESS_IS_NOT_PROOF_OF_DISCONNECTION"],
        ))
    records.extend(_pair_path_records(identity=resolved_identity, pair_evidence=pair_evidence))

    audit = _mapping(coverage.get("audit")) or {}
    artifact = _mapping(audit_artifact)
    if audit_artifact is not None and artifact is None:
        artifact = _plain(audit_artifact)
        artifact = artifact if isinstance(artifact, dict) else None
    audit_reasons: list[str] = []
    artifact_matches = bool(
        artifact
        and artifact.get("snapshot_id") == resolved_identity.snapshot_id
        and artifact.get("snapshot_version") == resolved_identity.snapshot_version
        and artifact.get("chain_id") == resolved_identity.chain_id
        and artifact.get("topology_version") == resolved_identity.topology_version
        and artifact.get("analysis_config_version") == resolved_identity.analysis_config_version
        and str(artifact.get("status") or "").upper() == "AVAILABLE"
        and str(artifact.get("mode") or "").upper() == "EXACT"
        and isinstance(artifact.get("artifact_fingerprint"), str)
        and bool(artifact.get("artifact_fingerprint"))
    )
    if artifact_matches:
        audit_status = "AVAILABLE"
        verdict = str(artifact.get("verdict") or "UNSPECIFIED")
        audit_summary = f"Structural Audit chính xác: {verdict}."
        audit_artifact_id = str(artifact.get("artifact_id") or "") or None
        audit_fingerprint = str(artifact["artifact_fingerprint"])
    else:
        source_status = str(audit.get("status") or "NOT_EVALUATED").upper()
        audit_status = "NOT_EVALUATED" if source_status in {"NOT_EVALUATED", "NOT_APPLICABLE"} else "UNAVAILABLE"
        audit_reasons = [
            "AUDIT_ARTIFACT_IDENTITY_MISMATCH"
            if artifact is not None
            else "AUDIT_NOT_EVALUATED"
            if audit_status == "NOT_EVALUATED"
            else "AUDIT_ARTIFACT_UNAVAILABLE"
        ]
        audit_summary = "Chưa có Structural Audit artifact chính xác cho identity này."
        audit_artifact_id = None
        audit_fingerprint = source_fingerprint
    records.append(_make_record(
        identity=resolved_identity,
        kind="AUDIT",
        status=audit_status,
        statement_kind="OBSERVED" if artifact_matches else "DERIVED",
        source_artifact_id=audit_artifact_id,
        source_fingerprint=audit_fingerprint,
        summary=audit_summary,
        reason_codes=audit_reasons,
        limitations=["AUDIT_GRAPH_IS_NOT_PHYSICAL_TOPOLOGY"],
    ))

    recommendations = _mapping(projection.get("recommendations")) or {}
    review = _mapping(review_result)
    review_payload = _mapping(review.get("result")) if review else None
    review_identity = _mapping(review.get("analysis_identity")) if review else None
    expected_review_identity = _mapping(projection.get("review_analysis_identity"))
    review_revision = _mapping(projection.get("review_artifact_revision")) or {}
    review_identity_matches = (
        review_identity is None
        or expected_review_identity is None
        or review_identity == expected_review_identity
    )
    review_completed = bool(
        (review_payload or {}).get("evaluation_completed")
        if review_payload is not None
        else recommendations.get("evaluation_completed")
    )
    if review is not None and not review_identity_matches:
        review_status = "UNAVAILABLE"
        review_reasons = ["REVIEW_IDENTITY_MISMATCH"]
        review_summary = "Review artifact không khớp analysis identity hiện tại."
        review_job_id = None
        review_fingerprint = None
    elif review_completed:
        review_status = "AVAILABLE"
        review_reasons = []
        count = (review_payload or recommendations).get("evaluated_count", 0)
        review_summary = f"Counterfactual Review đã hoàn tất; {count} phương án được đánh giá."
        review_job_id = str(review.get("job_id") or "") or None if review else None
        review_fingerprint = str(
            review_revision.get("fingerprint") or resolved_identity.input_fingerprint
        )
    else:
        raw_review_status = str(
            (review_payload or recommendations).get("status") or "NOT_EVALUATED"
        ).upper()
        review_status = "UNAVAILABLE" if raw_review_status == "UNAVAILABLE" else "NOT_EVALUATED"
        review_reasons = [
            "REVIEW_UNAVAILABLE" if review_status == "UNAVAILABLE" else "REVIEW_NOT_COMPLETED"
        ]
        review_summary = "Counterfactual Review chưa có kết quả đánh giá hoàn chỉnh."
        review_job_id = None
        review_fingerprint = str(
            review_revision.get("fingerprint") or resolved_identity.input_fingerprint
        )
    records.append(_make_record(
        identity=resolved_identity,
        kind="REVIEW",
        status=review_status,
        statement_kind="OBSERVED" if review_status == "AVAILABLE" else "DERIVED",
        source_artifact_id=review_job_id,
        source_fingerprint=review_fingerprint,
        summary=review_summary,
        reason_codes=review_reasons,
        limitations=["REVIEW_RECOMMENDATIONS_REQUIRE_OPERATOR_DECISION"],
    ))

    unique = {record["evidence_id"]: record for record in records}
    return [unique[key] for key in sorted(unique)]


def attach_evidence_references(
    *,
    identity: AnalysisIdentity | dict[str, Any],
    quality_assessment: dict[str, Any] | None,
    analytical_findings: list[dict[str, Any]] | None,
    records: list[dict[str, Any]],
) -> None:
    """Attach only same-identity typed records that support a deterministic claim.

    This is an additive presentation link: it does not change a score, finding,
    readiness gate, or the identity fingerprint. Findings whose source family
    is not represented by the evidence contract keep an empty reference list.
    """
    expected_identity = _identity(identity).to_payload()
    records_by_kind: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        evidence_id = record.get("evidence_id")
        kind = record.get("kind")
        if (
            not isinstance(evidence_id, str)
            or not evidence_id.startswith(_EVIDENCE_ID_PREFIX)
            or kind not in _ALLOWED_KINDS
            or record.get("analysis_identity") != expected_identity
        ):
            continue
        records_by_kind.setdefault(str(kind), []).append(record)

    def ids_for(
        kinds: tuple[str, ...],
        *,
        available_only: bool = False,
        unavailable_only: bool = False,
    ) -> list[str]:
        return sorted({
            str(record["evidence_id"])
            for kind in kinds
            for record in records_by_kind.get(kind, [])
            if not available_only or record.get("status") == "AVAILABLE"
            if not unavailable_only or record.get("status") != "AVAILABLE"
        })

    reason_kinds = {
        "SINGLETON_CHAIN": (),
        "INSUFFICIENT_ROLE_COVERAGE": ("MEMBERSHIP",),
        "INSUFFICIENT_INDEPENDENT_EVIDENCE": ("MAPPING", "TOPOLOGY_PATH", "AUDIT"),
        "TOPOLOGY_NOT_USED": ("MAPPING", "TOPOLOGY_PATH"),
        "TOPOLOGY_MAPPING_INCOMPLETE": ("MAPPING", "TOPOLOGY_PATH"),
        "TOPOLOGY_PAIR_COVERAGE_INCOMPLETE": ("MAPPING", "TOPOLOGY_PATH"),
        "TOPOLOGY_SOURCE_PARTIAL": ("MAPPING", "TOPOLOGY_PATH"),
        "AUDIT_INCOMPLETE": ("AUDIT",),
        "AUDIT_UNAVAILABLE": ("AUDIT",),
        "AUDIT_NOT_EVALUATED": ("AUDIT",),
        "REVIEW_UNAVAILABLE": ("REVIEW",),
        "REVIEW_NOT_COMPLETED": ("REVIEW",),
    }
    if isinstance(quality_assessment, dict):
        quality_assessment["evidence_ids"] = ids_for(
            ("MAPPING", "MEMBERSHIP", "TOPOLOGY_PATH", "AUDIT", "REVIEW")
        )
        reason_evidence_ids: dict[str, list[str]] = {}
        raw_reasons = quality_assessment.get("reason_codes")
        for raw_code in raw_reasons if isinstance(raw_reasons, list) else []:
            code = str(raw_code)
            kinds = reason_kinds.get(code)
            if kinds is None and code.startswith("TOPOLOGY_"):
                kinds = ("MAPPING", "TOPOLOGY_PATH")
            elif kinds is None and code.startswith("AUDIT_"):
                kinds = ("AUDIT",)
            elif kinds is None and code.startswith("REVIEW_"):
                kinds = ("REVIEW",)
            if kinds:
                reason_evidence_ids[code] = ids_for(kinds)
        quality_assessment["reason_evidence_ids"] = reason_evidence_ids

    finding_evidence = {
        "SHARED_TOPOLOGY_CONTEXT": ("MAPPING", "TOPOLOGY_PATH", True, False),
        "TOPOLOGY_EVIDENCE_GAP": ("MAPPING", "TOPOLOGY_PATH", False, True),
        # This hypothesis combines time ordering and structural context. The
        # typed path IDs refer only to its topology leg; no temporal record kind
        # exists yet, so the UI must retain the finding's explicit limitation.
        "PROPAGATION_COMPATIBLE_PATTERN": ("TOPOLOGY_PATH", True, False),
        "AUDIT_COHESION": ("AUDIT", True, False),
        "AUDIT_EVIDENCE_GAP": ("AUDIT", False, True),
    }
    for finding in analytical_findings or []:
        if not isinstance(finding, dict):
            continue
        reference = finding_evidence.get(str(finding.get("finding_id") or ""))
        if reference is None:
            finding["evidence_ids"] = []
            continue
        *kinds, available_only, unavailable_only = reference
        finding["evidence_ids"] = ids_for(
            tuple(kinds),
            available_only=available_only,
            unavailable_only=unavailable_only,
        )


def _encode_cursor(identity_digest: str, last_evidence_id: str) -> str:
    encoded = base64.urlsafe_b64encode(_canonical({
        "identity_digest": identity_digest,
        "last_evidence_id": last_evidence_id,
    }).encode("utf-8")).decode("ascii")
    return encoded.rstrip("=")


def _decode_cursor(cursor: str) -> dict[str, str]:
    if not isinstance(cursor, str) or not cursor or len(cursor) > 4096:
        raise InvalidEvidenceCursor("INVALID_EVIDENCE_CURSOR")
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, binascii.Error):
        raise InvalidEvidenceCursor("INVALID_EVIDENCE_CURSOR") from None
    if (
        not isinstance(payload, dict)
        or set(payload) != {"identity_digest", "last_evidence_id"}
        or not isinstance(payload.get("identity_digest"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", payload["identity_digest"])
        or not isinstance(payload.get("last_evidence_id"), str)
        or not payload["last_evidence_id"].startswith(_EVIDENCE_ID_PREFIX)
    ):
        raise InvalidEvidenceCursor("INVALID_EVIDENCE_CURSOR")
    return payload


def paginate_evidence_records(
    *,
    identity: AnalysisIdentity | dict[str, Any],
    records: list[dict[str, Any]],
    limit: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    resolved_identity = _identity(identity)
    if type(limit) is not int or not 1 <= limit <= _MAX_EVIDENCE_PAGE_SIZE:
        raise ValueError("EVIDENCE_LIMIT_OUT_OF_RANGE")
    identity_digest = _sha256(resolved_identity.to_payload())
    ordered = sorted(records, key=lambda record: str(record.get("evidence_id") or ""))
    start = 0
    if cursor:
        decoded = _decode_cursor(cursor)
        if decoded["identity_digest"] != identity_digest:
            raise StaleEvidenceCursor("STALE_EVIDENCE_CURSOR")
        last_id = decoded["last_evidence_id"]
        try:
            start = next(
                index + 1
                for index, record in enumerate(ordered)
                if record.get("evidence_id") == last_id
            )
        except StopIteration:
            raise StaleEvidenceCursor("STALE_EVIDENCE_CURSOR") from None
    page = ordered[start : start + limit]
    has_more = start + len(page) < len(ordered)
    next_cursor = (
        _encode_cursor(identity_digest, page[-1]["evidence_id"])
        if has_more and page
        else None
    )
    return {
        "analysis_identity": resolved_identity.to_payload(),
        "records": page,
        "truncated": has_more,
        "next_cursor": next_cursor,
    }


def build_evidence_bundle(
    *,
    identity: AnalysisIdentity | dict[str, Any],
    overview_projection: dict[str, Any] | None,
    pair_evidence: Any,
    audit_artifact: Any,
    review_result: Any,
    limit: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    resolved_identity = _identity(identity)
    records = build_evidence_records(
        identity=resolved_identity,
        overview_projection=overview_projection,
        pair_evidence=pair_evidence,
        audit_artifact=audit_artifact,
        review_result=review_result,
    )
    return paginate_evidence_records(
        identity=resolved_identity,
        records=records,
        limit=limit,
        cursor=cursor,
    )
