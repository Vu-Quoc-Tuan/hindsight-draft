"""Normalized pair-evidence channels (``K_pair``)."""

from .base import ChannelValue, EvidenceState, unavailable
from .contracts import ChannelFamily, DependencySemantic
from .common_dependency import (
    DEFAULT_LAMBDA_DEP,
    DEFAULT_THETA_CD,
    ActivePathIndex,
    DepUpstreamActivePath,
    DepUpstreamAncestor,
    DirectedHierarchy,
    VerifiedPath,
    build_active_path_index,
    build_dep_upstream_providers,
    build_directed_hierarchy,
    evaluate_shared_active_path,
    evaluate_shared_ancestor,
    specificity,
)
from .dependency import (
    DEFAULT_D_MAX,
    LOGICAL_RELATIONS,
    PHYSICAL_RELATIONS,
    SERVICE_RELATIONS,
    ResourceResolver,
    TopologyGraph,
    build_topology_graph,
    evaluate_dep_hop_channel,
)
from .topology_embedding import (
    TopologyEmbeddingModel,
    evaluate_topo_embedding_channel,
)
from .entity import (
    ENTITY_CHANNELS,
    REMOTE_CHANNEL,
    EntityChannelSpec,
    entity_channel,
    evaluate_entity_channels,
    evaluate_remote_channel,
)
from .evaluator import (
    DEFAULT_DELAY_THRESHOLD,
    DEFAULT_PAIR_DETAIL_LIMIT,
    EXACT_STATISTICS_MAX_MEMBERS,
    ChainEvidence,
    evaluate_chain_channels,
    evaluate_pair_channels,
)
from .cross_chain import (
    CrossChainEvidence,
    CrossGroupStatistics,
    exact_cross_chain_evidence,
)
from .indexed_evaluator import IndexedChainEvidence, evaluate_chain_indexed
from .indexed_statistics import build_indexed_statistics
from .rival_index import RivalFitIndex
from .failure_domain import (
    FailureDomainEvidence,
    failure_domains_for_chain,
    failure_domains_for_member,
)
from .pair_detail import PairChannelMatrix
from .semantic import (
    EMPTY_TAXONOMY,
    SCORE_SAME_CATEGORY,
    SCORE_SAME_FAMILY,
    SCORE_SAME_NAME,
    AlarmTaxonomy,
    evaluate_semantic_channel,
)
from .temporal import (
    DEFAULT_SILENT_GAP_SECONDS,
    BurstSegmentation,
    DelayDistribution,
    evaluate_burst_channel,
    evaluate_delay_channel,
    segment_bursts,
)

__all__ = [
    "DEFAULT_DELAY_THRESHOLD",
    "DEFAULT_D_MAX",
    "DEFAULT_LAMBDA_DEP",
    "DEFAULT_PAIR_DETAIL_LIMIT",
    "DEFAULT_SILENT_GAP_SECONDS",
    "DEFAULT_THETA_CD",
    "EMPTY_TAXONOMY",
    "ENTITY_CHANNELS",
    "EXACT_STATISTICS_MAX_MEMBERS",
    "LOGICAL_RELATIONS",
    "PHYSICAL_RELATIONS",
    "REMOTE_CHANNEL",
    "SCORE_SAME_CATEGORY",
    "SCORE_SAME_FAMILY",
    "SCORE_SAME_NAME",
    "SERVICE_RELATIONS",
    "ActivePathIndex",
    "AlarmTaxonomy",
    "BurstSegmentation",
    "ChainEvidence",
    "CrossChainEvidence",
    "CrossGroupStatistics",
    "ChannelFamily",
    "ChannelValue",
    "DelayDistribution",
    "DependencySemantic",
    "DepUpstreamActivePath",
    "DepUpstreamAncestor",
    "DirectedHierarchy",
    "EntityChannelSpec",
    "EvidenceState",
    "PairChannelMatrix",
    "ResourceResolver",
    "TopologyGraph",
    "TopologyEmbeddingModel",
    "VerifiedPath",
    "build_active_path_index",
    "build_dep_upstream_providers",
    "build_directed_hierarchy",
    "build_topology_graph",
    "entity_channel",
    "evaluate_burst_channel",
    "evaluate_chain_channels",
    "exact_cross_chain_evidence",
    "evaluate_chain_indexed",
    "evaluate_pair_channels",
    "IndexedChainEvidence",
    "RivalFitIndex",
    "FailureDomainEvidence",
    "failure_domains_for_chain",
    "failure_domains_for_member",
    "build_indexed_statistics",
    "evaluate_delay_channel",
    "evaluate_dep_hop_channel",
    "evaluate_topo_embedding_channel",
    "evaluate_entity_channels",
    "evaluate_remote_channel",
    "evaluate_semantic_channel",
    "evaluate_shared_active_path",
    "evaluate_shared_ancestor",
    "segment_bursts",
    "specificity",
    "unavailable",
]
