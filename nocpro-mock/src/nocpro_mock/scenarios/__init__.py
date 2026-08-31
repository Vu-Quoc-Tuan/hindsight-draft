"""Synthetic scenario definitions and generators (P0.5).

Synthetic data fills capability gaps the real exports cannot cover. It is always
stamped ``SYNTHETIC_TEST`` with generation metadata and can never validate
(ADR-0010, ADR-0026).
"""

from .context_generator import generate_operational_context
from .pair_metadata_generator import (
    GENERATOR_TYPE_DETERMINISTIC,
    SCORING_RULE_SAME_REFERENCE,
    generate_system_pair_metadata,
)
from .schema import (
    SYNTHETIC_TOKEN,
    ScenarioDefinition,
    ScenarioError,
    TopologySourceDefinition,
    is_synthetic_identifier,
    load_scenario,
    load_scenarios,
    parse_scenario,
    require_synthetic_identifiers,
)
from .sequence import (
    EvolutionEvent,
    ExpectedTransition,
    SequenceManifest,
    SequenceType,
    load_sequence_manifest,
    parse_sequence_manifest,
)
from .sequence_fixtures import (
    EVOLUTION_SPLIT_MERGE,
    HISTORY_POSITIVE_LIFT,
    SEQUENCE_FIXTURES,
    SequenceFixture,
)
from .snapshot_builder import SEQUENCE_EPOCH, build_synthetic_snapshot
from .topology_generators import (
    TOPOLOGY_LAYER_SYNTHETIC,
    generate_active_paths,
    generate_dependency_hierarchy,
    generate_failure_domains,
    generate_integrated_topology,
)

__all__ = [
    "EVOLUTION_SPLIT_MERGE",
    "GENERATOR_TYPE_DETERMINISTIC",
    "HISTORY_POSITIVE_LIFT",
    "SCORING_RULE_SAME_REFERENCE",
    "SEQUENCE_EPOCH",
    "SEQUENCE_FIXTURES",
    "SYNTHETIC_TOKEN",
    "TOPOLOGY_LAYER_SYNTHETIC",
    "TopologySourceDefinition",
    "EvolutionEvent",
    "ExpectedTransition",
    "ScenarioDefinition",
    "ScenarioError",
    "SequenceFixture",
    "SequenceManifest",
    "SequenceType",
    "build_synthetic_snapshot",
    "generate_active_paths",
    "generate_dependency_hierarchy",
    "generate_failure_domains",
    "generate_integrated_topology",
    "generate_operational_context",
    "generate_system_pair_metadata",
    "is_synthetic_identifier",
    "load_scenario",
    "load_scenarios",
    "load_sequence_manifest",
    "parse_scenario",
    "parse_sequence_manifest",
    "require_synthetic_identifiers",
]
