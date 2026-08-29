"""Explicit projections from analysis objects into stable HTTP schemas."""

from __future__ import annotations

from dataclasses import asdict

from channels import ChannelValue
from tier1b import ChainAnalysis
from tier2 import Tier2JobView

from .schemas import (
    ChainAnalysisView,
    DeepDiveView,
    DescriptorView,
    GrayBoxView,
    GroupFitView,
    JobView,
    MarginView,
    MemberView,
    PairEvidenceView,
    StructuralAuditView,
)


def descriptor_view(descriptor) -> DescriptorView:
    metrics = descriptor.metrics
    return DescriptorView(
        kind=descriptor.kind.value,
        label=descriptor.label,
        coverage=metrics.coverage,
        precision_global=metrics.precision,
        precision_local=descriptor.precision_local,
        false_positive_rate=metrics.false_positive_rate,
        lift=metrics.lift,
        f1=metrics.f1,
    )


def chain_analysis_view(analysis: ChainAnalysis, package) -> ChainAnalysisView:
    members = []
    for alarm_id, item in analysis.members.items():
        alarm = package.alarms[alarm_id]
        members.append(
            MemberView(
                alarm_id=alarm_id,
                alarm_name=alarm.alarm_name,
                device_code=alarm.device_code,
                node_reference=alarm.node_reference,
                canonical_start_time=alarm.canonical_start_time,
                role=item.role.verdict.value,
                membership_support=item.support.support,
                availability_coverage=item.role.gate.availability_coverage,
                computable_groups=item.role.gate.computable_groups,
                representativeness=item.representativeness,
                group_fits=[
                    GroupFitView(
                        derivation_tag=group.derivation_tag,
                        fit=group.fit,
                        channels=[fit.channel_id for fit in group.channel_fits],
                    )
                    for group in item.support.group_fits
                ],
                margins=[
                    MarginView(
                        compared_chain_id=margin.compared_chain_id,
                        margin=margin.margin,
                        computable_groups=margin.shared_groups,
                    )
                    for margin in item.margins
                ],
                redundancy_role=(
                    item.redundancy.role.value if item.redundancy else None
                ),
                failure_domains=[
                    domain.failure_domain_id for domain in item.failure_domains
                ],
            )
        )
    return ChainAnalysisView(
        chain_id=analysis.chain_id,
        title=analysis.auto_title or f"Chain {analysis.chain_id}",
        member_count=analysis.member_count,
        singleton=analysis.singleton,
        statistics_mode=analysis.evidence.statistics_mode.value,
        audit_graph_mode=analysis.evidence.audit_graph_mode.value,
        pair_materialization=analysis.evidence.pair_materialization.value,
        config_version=analysis.config_version or "unknown",
        graybox=GrayBoxView(
            mode="GRAY_BOX" if analysis.graybox.available else "BLACK_BOX",
            merge_strategy=analysis.graybox.merge_strategy,
            rules=len(analysis.graybox.rules),
            characteristics=len(analysis.graybox.characteristics),
            pair_facts=len(analysis.graybox.pair_facts),
            unavailable_capabilities=list(
                analysis.graybox.unavailable_capabilities
            ),
        ),
        descriptors=[
            descriptor_view(item)
            for item in (*analysis.descriptors.identity, *analysis.descriptors.contrastive)
        ],
        members=members,
        role_counts=analysis.role_counts(),
        phase_durations=analysis.phase_durations,
    )


def pair_evidence_view(value: ChannelValue) -> PairEvidenceView:
    family = (
        value.channel_family.value if value.channel_family else value.channel_id
    )
    return PairEvidenceView(
        channel_family=family,
        provider_id=value.channel_id if value.channel_family else None,
        dependency_semantic=(
            value.dependency_semantic.value if value.dependency_semantic else None
        ),
        state=value.state.value,
        score=value.positive_score if value.availability else None,
        threshold=value.threshold,
        negative_score=value.negative_score if value.availability else None,
        detail=value.detail,
        derivation_tag=value.derivation_tag,
        provenance_class=value.provenance_class.value,
        provenance_subtype=(
            value.provenance_subtype.value if value.provenance_subtype else None
        ),
        source_ref=value.source_ref,
    )


def deep_dive_view(result) -> DeepDiveView:
    audit = result.structural_audit
    best = audit.best_cut
    return DeepDiveView(
        chain_id=result.chain_id,
        audit_graph_mode=result.audit_graph_mode.value,
        structural_audit=StructuralAuditView(
            verdict=audit.verdict.value,
            reason=audit.reason,
            epsilon=audit.epsilon,
            best_cut_label=best.candidate.label if best else None,
            best_cut_phi=best.conductance.phi if best else None,
        ),
        over_merge_strength=result.over_merge.strength.value,
        over_merge_narrative=result.over_merge.narrative,
        similar_chains=[asdict(item) for item in result.similar_chains],
        similarity_status=result.similarity_status,
        similarity_unavailable_reason=result.similarity_unavailable_reason,
        similarity_model_version=result.similarity_model_version,
        similarity_trained_until_exclusive=(
            result.similarity_trained_until_exclusive
        ),
        similarity_corpus_policy=result.similarity_corpus_policy,
        similarity_model_update_policy=result.similarity_model_update_policy,
        taxonomy_status=result.taxonomy_status,
        taxonomy_reason=result.taxonomy_reason,
        active_fingerprint_blocks=list(result.active_fingerprint_blocks),
    )


def job_view(view: Tier2JobView) -> JobView:
    return JobView(
        job_id=view.job_id,
        chain_id=view.chain_id,
        status=view.status.value,
        progress_percent=view.progress_percent,
        cache_hit=view.cache_hit,
        result=deep_dive_view(view.result) if view.result is not None else None,
        error=view.error,
    )
