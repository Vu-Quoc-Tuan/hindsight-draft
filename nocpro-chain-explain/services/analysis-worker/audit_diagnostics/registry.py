"""Resolve the exact evaluator's channel and effective-group registry."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from channels.dependency import (
    CHANNEL_ID as DEP_HOP_CHANNEL_ID,
    DERIVATION_TAG as DEP_HOP_DERIVATION_TAG,
    PHYSICAL_RELATIONS,
    build_topology_graph,
)
from channels.entity import ENTITY_CHANNELS, REMOTE_CHANNEL, REMOTE_DERIVATION
from channels.semantic import CHANNEL_ID as SEMANTIC_CHANNEL_ID, DERIVATION_TAG as SEMANTIC_DERIVATION_TAG
from channels.temporal import (
    BURST_CHANNEL,
    BURST_DERIVATION,
    DELAY_CHANNEL,
    DELAY_DERIVATION,
)
from libs.contracts import IngestedPackage
from libs.provenance import (
    EffectiveGroupKey,
    NormalizedChannel,
    ProvenanceClass,
    ProvenanceSubtype,
    baseline_eligibility,
)

from .contracts import GroupKey
from .scope import ScopePolicy


@dataclass(frozen=True)
class ResolvedChannelRegistry:
    channel_ids: tuple[str, ...]
    group_channels: dict[GroupKey, tuple[str, ...]]
    channel_groups: dict[str, GroupKey]
    execution_profile_digest: str
    group_registry_digest: str
    complete: bool
    issues: tuple[str, ...]


def resolve_execution_registry(
    package: IngestedPackage,
    policy: ScopePolicy,
) -> ResolvedChannelRegistry:
    """Resolve static and source-bound providers before inspecting pair scores."""
    channel_semantics: dict[str, tuple[str, ProvenanceClass, ProvenanceSubtype | None]] = {}
    for channel_id, (_, derivation_tag) in ENTITY_CHANNELS.items():
        channel_semantics[channel_id] = (
            derivation_tag, ProvenanceClass.POST_HOC, None
        )
    channel_semantics[REMOTE_CHANNEL] = (
        REMOTE_DERIVATION, ProvenanceClass.POST_HOC, None
    )
    channel_semantics[SEMANTIC_CHANNEL_ID] = (
        SEMANTIC_DERIVATION_TAG, ProvenanceClass.POST_HOC, None
    )
    channel_semantics[BURST_CHANNEL] = (
        BURST_DERIVATION, ProvenanceClass.POST_HOC, None
    )
    channel_semantics[DELAY_CHANNEL] = (
        DELAY_DERIVATION, ProvenanceClass.POST_HOC, None
    )

    topology = None
    if package.topology.get("edges") or ():
        topology = build_topology_graph(package, relation_types=PHYSICAL_RELATIONS)
    dep_class = topology.provenance_class if topology is not None else ProvenanceClass.EXTERNAL_OPERATIONAL
    dep_subtype = topology.provenance_subtype if topology is not None else ProvenanceSubtype.TOPOLOGY_EXTERNAL
    channel_semantics[DEP_HOP_CHANNEL_ID] = (
        DEP_HOP_DERIVATION_TAG, dep_class, dep_subtype
    )

    channel_ids = tuple(sorted(channel_semantics))
    expected_exact = {item.channel_id for item in policy.channels if item.channel_id is not None}
    expected_prefixes = tuple(
        item.channel_id_prefix for item in policy.channels if item.channel_id_prefix is not None
    )
    issues: list[str] = []
    for channel_id in channel_ids:
        if policy.definition_for(channel_id) is None:
            issues.append(f"SCOPE_RULE_UNDEFINED:{channel_id}")
    missing_exact = expected_exact - set(channel_ids)
    if missing_exact:
        issues.extend(f"EXPECTED_CHANNEL_NOT_RESOLVED:{item}" for item in sorted(missing_exact))
    for prefix in expected_prefixes:
        if not any(channel_id.startswith(prefix) for channel_id in channel_ids):
            issues.append(f"EXPECTED_DYNAMIC_CHANNEL_NOT_RESOLVED:{prefix}")

    channel_groups: dict[str, GroupKey] = {}
    group_channels_mutable: dict[GroupKey, list[str]] = {}
    for channel_id, (tag, provenance, subtype) in channel_semantics.items():
        eligibility = baseline_eligibility(provenance, subtype)
        effective = EffectiveGroupKey(
            derivation_tag=tag,
            provenance_class=provenance,
            explain_eligible=eligibility.explain_eligible,
            role_eligible=eligibility.role_eligible,
            audit_eligible=eligibility.audit_eligible,
        )
        group_key = GroupKey.from_effective_key(effective)
        channel_groups[channel_id] = group_key
        group_channels_mutable.setdefault(group_key, []).append(channel_id)

    group_channels = {
        key: tuple(sorted(value)) for key, value in group_channels_mutable.items()
    }
    group_payload = [
        {"key": key.model_dump(mode="json"), "channel_ids": group_channels[key]}
        for key in sorted(group_channels, key=_group_sort_key)
    ]
    profile_payload = {
        "binding": "tier2.audit_analysis.evaluate_chain_channels",
        "channels": channel_ids,
    }
    return ResolvedChannelRegistry(
        channel_ids=channel_ids,
        group_channels=group_channels,
        channel_groups=channel_groups,
        execution_profile_digest=_digest(profile_payload),
        group_registry_digest=_digest(group_payload),
        complete=not issues,
        issues=tuple(sorted(issues)),
    )


def _group_sort_key(key: GroupKey) -> tuple[str, str, bool, bool, bool]:
    return (
        key.derivation_tag,
        key.provenance_class.value,
        key.explain_eligible,
        key.role_eligible,
        key.audit_eligible,
    )


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()
