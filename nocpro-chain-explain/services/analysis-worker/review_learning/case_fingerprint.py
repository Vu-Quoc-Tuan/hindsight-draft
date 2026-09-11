"""5-block deterministic case fingerprinting for counterfactual candidates.

Extracts candidate-local features across:
1. chain_context
2. evidence_shape
3. temporal_shape
4. topology_shape (candidate-local, strictly avoiding global node counts)
5. operation_pattern
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence
from review_learning.contracts import canonical_json_hash

FINGERPRINT_SCHEMA_VERSION = "cf-case-v1"


def extract_candidate_case_blocks(
    *,
    candidate: Mapping[str, Any],
    chain_id: str,
    chain_alarms: Sequence[Any],
    temporal_shape: Mapping[str, Any] | None = None,
    topology_summary: Mapping[str, Any] | None = None,
    channel_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract 5 deterministic blocks for a candidate."""
    # 1. Chain Context Block
    alarm_count = len(chain_alarms)
    device_codes = {getattr(a, "device_code", None) for a in chain_alarms if getattr(a, "device_code", None)}
    alarm_names = {getattr(a, "alarm_name", None) for a in chain_alarms if getattr(a, "alarm_name", None)}
    domains = set()
    for a in chain_alarms:
        fds = getattr(a, "failure_domains", None) or []
        for fd in fds:
            domains.add(fd)

    chain_context = {
        "alarm_count": alarm_count,
        "device_count": len(device_codes),
        "unique_alarm_type_count": len(alarm_names),
        "failure_domain_count": len(domains),
    }

    # 2. Evidence Shape Block
    evidence_shape = {
        "channels_available": (channel_summary or {}).get("channels_available", 0),
        "channels_total": (channel_summary or {}).get("channels_total", 0),
        "has_cross_chain_evidence": (channel_summary or {}).get("has_cross_chain", False),
    }

    # 3. Temporal Shape Block
    temp = temporal_shape or {}
    temporal_block = {
        "status": temp.get("status", "UNAVAILABLE"),
        "coverage_ratio": (temp.get("before") or {}).get("coverage_ratio", 0.0),
        "mean_positive_score": (temp.get("before") or {}).get("mean_positive_score", 0.0),
        "delta_mean_score": (temp.get("delta") or {}).get("delta_mean_positive_score", 0.0),
    }

    # 4. Topology Shape Block (Candidate-local only)
    top = topology_summary or {}
    topology_block = {
        "status": top.get("status", "UNAVAILABLE"),
        "relation_type": top.get("relation_type", "NONE"),
        "affected_alarm_count": top.get("affected_alarm_count", alarm_count),
        "mapped_alarm_count": top.get("mapped_alarm_count", 0),
        "mapping_coverage": top.get("mapping_coverage", 0.0),
        "eligible_proximity_pairs": top.get("eligible_proximity_pair_count", 0),
    }

    # 5. Operation Pattern Block
    op = candidate.get("operation", "UNKNOWN")
    delta = candidate.get("partition_delta") or {}
    removed_count = len(delta.get("removed_alarms", []))
    partitions = delta.get("partitions") or delta.get("split_partitions") or []
    split_count = len(partitions) if isinstance(partitions, list) else 0

    operation_pattern = {
        "operation": op,
        "removed_alarm_count": removed_count,
        "split_partition_count": split_count,
        "relative_size_ratio": round((alarm_count - removed_count) / alarm_count, 4) if alarm_count > 0 else 1.0,
    }

    return {
        "chain_context": chain_context,
        "evidence_shape": evidence_shape,
        "temporal_shape": temporal_block,
        "topology_shape": topology_block,
        "operation_pattern": operation_pattern,
    }


def compute_case_fingerprint_payload(
    blocks: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], str]:
    """Compute deterministic block hashes and master fingerprint hash."""
    block_hashes = {
        block_name: canonical_json_hash(block_data)
        for block_name, block_data in sorted(blocks.items())
    }
    master_payload = {
        "schema_version": FINGERPRINT_SCHEMA_VERSION,
        "block_hashes": block_hashes,
        "blocks": {k: dict(v) for k, v in sorted(blocks.items())},
    }
    master_hash = canonical_json_hash(master_payload)
    return master_payload, master_hash
