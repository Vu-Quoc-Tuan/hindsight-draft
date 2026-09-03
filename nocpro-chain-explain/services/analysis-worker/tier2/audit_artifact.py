"""Compact immutable exact Structural Audit artifact for Counterfactual Review."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from uuid import uuid4

from audit import (
    AuditVerdict,
    Candidate,
    CandidateSource,
    ConductanceResult,
    ScoredCandidate,
    StructuralAuditResult,
)


AUDIT_ARTIFACT_VERSION = "review-audit-v1"
AUDIT_ANALYSIS_VERSION = "tier2-audit-v1"


def chain_membership_fingerprint(members: tuple[str, ...] | list[str]) -> str:
    payload = json.dumps(sorted(members), separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ReviewAuditCut:
    source: str
    members: tuple[str, ...]
    label: str
    size_s: int
    size_complement: int
    phi: float | None
    feasible: bool
    reason: str | None

    def to_scored_candidate(self) -> ScoredCandidate:
        candidate = Candidate(
            source=CandidateSource(self.source),
            members=frozenset(self.members),
            label=self.label,
        )
        return ScoredCandidate(
            candidate=candidate,
            conductance=ConductanceResult(
                label=self.label,
                size_s=self.size_s,
                size_complement=self.size_complement,
                phi=self.phi,
                feasible=self.feasible,
                reason=self.reason,
            ),
        )


@dataclass(frozen=True)
class ReviewAuditArtifact:
    artifact_id: str
    artifact_version: str
    artifact_fingerprint: str
    snapshot_id: str
    snapshot_version: str
    chain_id: str
    chain_fingerprint: str
    analysis_version: str
    analysis_config_version: str
    status: str
    mode: str
    chain_size: int
    verdict: str
    epsilon: float | None
    reason: str
    best_cut_index: int | None
    scored_cuts: tuple[ReviewAuditCut, ...]
    created_at: str

    @property
    def structural_audit(self) -> StructuralAuditResult:
        scored = tuple(cut.to_scored_candidate() for cut in self.scored_cuts)
        best = scored[self.best_cut_index] if self.best_cut_index is not None else None
        return StructuralAuditResult(
            chain_id=self.chain_id,
            verdict=AuditVerdict(self.verdict),
            best_cut=best,
            scored_candidates=scored,
            epsilon=self.epsilon,
            reason=self.reason,
        )

    def is_compatible(
        self,
        *,
        snapshot_id: str,
        snapshot_version: str,
        chain_id: str,
        members: tuple[str, ...] | list[str],
        analysis_version: str,
        analysis_config_version: str,
    ) -> bool:
        return (
            self.status == "AVAILABLE"
            and self.mode == "EXACT"
            and self.snapshot_id == snapshot_id
            and self.snapshot_version == snapshot_version
            and self.chain_id == chain_id
            and self.chain_fingerprint == chain_membership_fingerprint(members)
            and self.analysis_version == analysis_version
            and self.analysis_config_version == analysis_config_version
            and self.artifact_fingerprint == _fingerprint(_payload_without_fingerprint(self))
        )


def _cut_from_scored(value: ScoredCandidate) -> ReviewAuditCut:
    result = value.conductance
    return ReviewAuditCut(
        source=value.candidate.source.value,
        members=tuple(sorted(value.candidate.members)),
        label=value.candidate.label,
        size_s=result.size_s,
        size_complement=result.size_complement,
        phi=result.phi,
        feasible=result.feasible,
        reason=result.reason,
    )


def _cut_to_dict(value: ReviewAuditCut) -> dict:
    return {
        "source": value.source,
        "members": list(value.members),
        "label": value.label,
        "conductance": {
            "size_s": value.size_s,
            "size_complement": value.size_complement,
            "phi": value.phi,
            "feasible": value.feasible,
            "reason": value.reason,
        },
    }


def _payload_without_fingerprint(value: ReviewAuditArtifact) -> dict:
    return {
        "artifact_id": value.artifact_id,
        "artifact_version": value.artifact_version,
        "snapshot_id": value.snapshot_id,
        "snapshot_version": value.snapshot_version,
        "chain_id": value.chain_id,
        "chain_fingerprint": value.chain_fingerprint,
        "analysis_version": value.analysis_version,
        "analysis_config_version": value.analysis_config_version,
        "status": value.status,
        "mode": value.mode,
        "chain_size": value.chain_size,
        "verdict": value.verdict,
        "epsilon": value.epsilon,
        "reason": value.reason,
        "best_cut_index": value.best_cut_index,
        "scored_cuts": [_cut_to_dict(cut) for cut in value.scored_cuts],
        "created_at": value.created_at,
    }


def _fingerprint(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def build_review_audit_artifact(
    *,
    snapshot_id: str,
    snapshot_version: str,
    chain_id: str,
    members: tuple[str, ...] | list[str],
    structural_audit: StructuralAuditResult,
    analysis_version: str,
    analysis_config_version: str,
    artifact_id: str | None = None,
    created_at: str | None = None,
) -> ReviewAuditArtifact:
    if structural_audit.chain_id != chain_id:
        raise ValueError("Structural Audit chain identity mismatch")
    cuts = tuple(_cut_from_scored(value) for value in structural_audit.scored_candidates)
    best_cut_index = None
    if structural_audit.best_cut is not None:
        try:
            best_cut_index = structural_audit.scored_candidates.index(
                structural_audit.best_cut
            )
        except ValueError as exc:
            raise ValueError("best cut is absent from scored candidates") from exc
    provisional = ReviewAuditArtifact(
        artifact_id=artifact_id or uuid4().hex,
        artifact_version=AUDIT_ARTIFACT_VERSION,
        artifact_fingerprint="",
        snapshot_id=snapshot_id,
        snapshot_version=snapshot_version,
        chain_id=chain_id,
        chain_fingerprint=chain_membership_fingerprint(members),
        analysis_version=analysis_version,
        analysis_config_version=analysis_config_version,
        status="AVAILABLE",
        mode="EXACT",
        chain_size=len(members),
        verdict=structural_audit.verdict.value,
        epsilon=structural_audit.epsilon,
        reason=structural_audit.reason,
        best_cut_index=best_cut_index,
        scored_cuts=cuts,
        created_at=created_at or datetime.now(timezone.utc).isoformat(),
    )
    return ReviewAuditArtifact(
        **{
            **vars(provisional),
            "artifact_fingerprint": _fingerprint(
                _payload_without_fingerprint(provisional)
            ),
        }
    )


def audit_artifact_to_dict(value: ReviewAuditArtifact) -> dict:
    return {
        **_payload_without_fingerprint(value),
        "artifact_fingerprint": value.artifact_fingerprint,
    }


def audit_artifact_from_dict(
    payload: dict, *, verify_fingerprint: bool = True
) -> ReviewAuditArtifact:
    if payload.get("artifact_version") != AUDIT_ARTIFACT_VERSION:
        raise ValueError("unsupported Audit artifact version")
    if payload.get("status") != "AVAILABLE" or payload.get("mode") != "EXACT":
        raise ValueError("Review requires an available exact Audit artifact")
    cuts = []
    for value in payload.get("scored_cuts", ()):
        conductance = value["conductance"]
        cuts.append(
            ReviewAuditCut(
                source=value["source"],
                members=tuple(value["members"]),
                label=value["label"],
                size_s=int(conductance["size_s"]),
                size_complement=int(conductance["size_complement"]),
                phi=(
                    float(conductance["phi"])
                    if conductance.get("phi") is not None
                    else None
                ),
                feasible=bool(conductance["feasible"]),
                reason=conductance.get("reason"),
            )
        )
    artifact = ReviewAuditArtifact(
        artifact_id=payload["artifact_id"],
        artifact_version=payload["artifact_version"],
        artifact_fingerprint=payload["artifact_fingerprint"],
        snapshot_id=payload["snapshot_id"],
        snapshot_version=payload["snapshot_version"],
        chain_id=payload["chain_id"],
        chain_fingerprint=payload["chain_fingerprint"],
        analysis_version=payload["analysis_version"],
        analysis_config_version=payload["analysis_config_version"],
        status=payload["status"],
        mode=payload["mode"],
        chain_size=int(payload["chain_size"]),
        verdict=payload["verdict"],
        epsilon=float(payload["epsilon"]) if payload.get("epsilon") is not None else None,
        reason=payload["reason"],
        best_cut_index=payload.get("best_cut_index"),
        scored_cuts=tuple(cuts),
        created_at=payload["created_at"],
    )
    if artifact.best_cut_index is not None and not (
        0 <= artifact.best_cut_index < len(artifact.scored_cuts)
    ):
        raise ValueError("Audit artifact best_cut_index is invalid")
    expected = _fingerprint(_payload_without_fingerprint(artifact))
    if verify_fingerprint and artifact.artifact_fingerprint != expected:
        raise ValueError("Audit artifact fingerprint mismatch")
    return artifact
