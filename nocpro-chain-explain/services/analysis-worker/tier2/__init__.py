"""Tier-2 on-demand analysis entry points."""

from .audit_analysis import (
    AuditExecutionPolicy,
    SimilarityQueryContext,
    Tier2AuditAnalysis,
    analyze_structural_audit,
)
from .jobs import (
    JobStatus,
    Tier2JobManager,
    Tier2JobView,
    Tier2Submission,
)
from .evidence_attribution import (
    AttributionExecutionPolicy,
    AttributionMode,
    AttributionReason,
    AttributionStatus,
    EvidenceCoverageAttributionResult,
    EvidenceCoverageContribution,
    compute_evidence_coverage_attribution,
)
from .attribution_evaluation import (
    RANDOMIZATION_ALGORITHM,
    AttributionDeletionEvaluationResult,
    AttributionEvaluationMode,
    AttributionEvaluationReason,
    AttributionEvaluationStatus,
    DeletionCurve,
    RandomDeletionBaseline,
    evaluate_attribution_deletion,
)
from .topology_hypotheses import (
    TopologyHypothesesResult,
    analyze_topology_hypotheses,
)

__all__ = [
    "AuditExecutionPolicy",
    "SimilarityQueryContext",
    "Tier2AuditAnalysis",
    "analyze_structural_audit",
    "JobStatus",
    "Tier2JobManager",
    "Tier2JobView",
    "Tier2Submission",
    "TopologyHypothesesResult",
    "analyze_topology_hypotheses",
    "AttributionExecutionPolicy",
    "AttributionMode",
    "AttributionReason",
    "AttributionStatus",
    "EvidenceCoverageAttributionResult",
    "EvidenceCoverageContribution",
    "compute_evidence_coverage_attribution",
    "RANDOMIZATION_ALGORITHM",
    "AttributionDeletionEvaluationResult",
    "AttributionEvaluationMode",
    "AttributionEvaluationReason",
    "AttributionEvaluationStatus",
    "DeletionCurve",
    "RandomDeletionBaseline",
    "evaluate_attribution_deletion",
]
