"""Read-only access to the canonical Input Contract.

ADR-MOCK/docs 01: the mock SHALL NOT import Explain business logic. Importing
the versioned *contract artifact* is the one allowed coupling, so this module is
the single place that resolves it. Everything else in the mock imports from here.

The contract lives in the sibling repository (ADR-0002). It is located by path
rather than by installed package so the two repositories stay independent.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_CONTRACT_PACKAGE = "nocpro_contract_v1"
_DEFAULT_RELATIVE_PATH = Path("../nocpro-chain-explain/contracts/v1")


class ContractUnavailable(RuntimeError):
    """Raised when the canonical contract cannot be located.

    Fail closed: the mock must not fall back to a locally invented schema.
    """


def _candidate_roots() -> list[Path]:
    here = Path(__file__).resolve()
    repo_root = here.parents[2]
    return [
        (repo_root / _DEFAULT_RELATIVE_PATH).resolve(),
        (repo_root.parent / "nocpro-chain-explain/contracts/v1").resolve(),
    ]


def _load() -> ModuleType:
    if _CONTRACT_PACKAGE in sys.modules:
        return sys.modules[_CONTRACT_PACKAGE]

    for root in _candidate_roots():
        init = root / "__init__.py"
        if not init.is_file():
            continue
        spec = importlib.util.spec_from_file_location(
            _CONTRACT_PACKAGE, init, submodule_search_locations=[str(root)]
        )
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        sys.modules[_CONTRACT_PACKAGE] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            del sys.modules[_CONTRACT_PACKAGE]
            raise
        return module

    searched = "\n  ".join(str(p) for p in _candidate_roots())
    raise ContractUnavailable(
        "Canonical Input Contract v1 not found. The mock refuses to invent a "
        f"local schema (ADR-0002). Searched:\n  {searched}"
    )


contract = _load()

SCHEMA_VERSION = contract.SCHEMA_VERSION
ActivePath = contract.ActivePath
Alarm = contract.Alarm
AlarmResourceMapping = contract.AlarmResourceMapping
AttributeConfig = contract.AttributeConfig
Chain = contract.Chain
ChainCharacteristic = contract.ChainCharacteristic
ChainMembership = contract.ChainMembership
ChainRule = contract.ChainRule
ChainingUsage = contract.ChainingUsage
ChainingUsageAssessment = contract.ChainingUsageAssessment
ContextType = contract.ContextType
ContractViolation = contract.ContractViolation
CoverageScope = contract.CoverageScope
FailureDomain = contract.FailureDomain
FailureDomainType = contract.FailureDomainType
GenerationMetadata = contract.GenerationMetadata
MappingMethod = contract.MappingMethod
MappingStatus = contract.MappingStatus
MockSnapshotPackage = contract.MockSnapshotPackage
OperationalContext = contract.OperationalContext
PairMetadata = contract.PairMetadata
PairMetadataBatch = contract.PairMetadataBatch
ProvenanceClass = contract.ProvenanceClass
ProvenanceManifest = contract.ProvenanceManifest
ProvenanceSubtype = contract.ProvenanceSubtype
QualityFlag = contract.QualityFlag
QualityStatus = contract.QualityStatus
RelationType = contract.RelationType
Snapshot = contract.Snapshot
SnapshotStatus = contract.SnapshotStatus
SourceKind = contract.SourceKind
SourceRecord = contract.SourceRecord
SystemMetadata = contract.SystemMetadata
SystemPairStatus = contract.SystemPairStatus
SystemSemantic = contract.SystemSemantic
TIMEWINDOW_VETO_SENTINEL = contract.TIMEWINDOW_VETO_SENTINEL
Topology = contract.Topology
TopologyEdge = contract.TopologyEdge
TopologyNode = contract.TopologyNode
TopologyRef = getattr(contract, "TopologyRef", None)
canonical_topology_version = getattr(contract, "canonical_topology_version", None)
ValidationResult = contract.ValidationResult

is_validation_eligible = contract.is_validation_eligible
package_to_dict = contract.package_to_dict
package_to_json = contract.package_to_json
parse_package = contract.parse_package
validate_package = contract.validate_package

__all__ = [
    "ContractUnavailable",
    "SCHEMA_VERSION",
    "ActivePath",
    "Alarm",
    "AlarmResourceMapping",
    "AttributeConfig",
    "Chain",
    "ChainCharacteristic",
    "ChainMembership",
    "ChainRule",
    "ChainingUsage",
    "ChainingUsageAssessment",
    "ContextType",
    "ContractViolation",
    "CoverageScope",
    "FailureDomain",
    "FailureDomainType",
    "GenerationMetadata",
    "MappingMethod",
    "MappingStatus",
    "MockSnapshotPackage",
    "OperationalContext",
    "PairMetadata",
    "PairMetadataBatch",
    "ProvenanceClass",
    "ProvenanceManifest",
    "ProvenanceSubtype",
    "QualityFlag",
    "QualityStatus",
    "RelationType",
    "Snapshot",
    "SnapshotStatus",
    "SourceKind",
    "SourceRecord",
    "SystemMetadata",
    "SystemPairStatus",
    "SystemSemantic",
    "TIMEWINDOW_VETO_SENTINEL",
    "Topology",
    "TopologyEdge",
    "TopologyNode",
    "TopologyRef",
    "ValidationResult",
    "canonical_topology_version",

    "is_validation_eligible",
    "package_to_dict",
    "package_to_json",
    "parse_package",
    "validate_package",
]
