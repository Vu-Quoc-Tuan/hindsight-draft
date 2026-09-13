"""Explicit projections from analysis objects into stable HTTP schemas."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime

from channels import ChannelValue
from tier1b import ChainAnalysis
from tier2 import Tier2JobView
from tier2 import AuditVisualization
from tier2.counterfactual import CounterfactualJobView as DomainCounterfactualJobView
from tier2.counterfactual.public_contract import public_review_result
from tier2.topology_hypotheses import (
    DependencyScopeResult,
    DominatorResult,
    PropagationResult,
    ResourceDetails,
    TopologyHypothesesResult,
)

from .schemas import (
    ChainAnalysisView,
    CounterfactualJobView,
    OperatorFeedbackView,
    AISuggestionView,
    AuditVisualizationArtifactView,
    AuditVisualizationEdgeView,
    AuditVisualizationNodeView,
    AuditVisualizationView,
    DeepDiveView,
    DescriptorView,
    EvidenceCoverageAttributionView,
    EvolutionView,
    GrayBoxView,
    GroupFitView,
    JobView,
    MarginView,
    MemberView,
    PairEvidenceView,
    StructuralAuditView,
    DependencyScopeView,
    DominatorView,
    PropagationDiagnosticsView,
    PropagationEdgeHypothesisView,
    PropagationNodeScoreView,
    PropagationView,
    ResourceDetailsView,
    TopologyHypothesesView,
)


def audit_visualization_view(value: AuditVisualization) -> AuditVisualizationView:
    return AuditVisualizationView(
        status=value.status,
        reason=value.reason,
        projection_version=value.projection_version,
        selection_strategy=value.selection_strategy,
        max_nodes=value.max_nodes,
        max_edges=value.max_edges,
        total_node_count=value.total_node_count,
        shown_node_count=value.shown_node_count,
        hidden_node_count=value.hidden_node_count,
        total_edge_count=value.total_edge_count,
        shown_edge_count=value.shown_edge_count,
        hidden_edge_count=value.hidden_edge_count,
        truncated=value.truncated,
        nodes=[
            AuditVisualizationNodeView(
                alarm_id=node.alarm_id,
                weighted_degree=node.weighted_degree,
                cut_side=node.cut_side,
                structural_role=node.structural_role,
            )
            for node in value.nodes
        ],
        edges=[
            AuditVisualizationEdgeView(
                source_alarm_id=edge.source_alarm_id,
                target_alarm_id=edge.target_alarm_id,
                weight=edge.weight,
                supporting_groups=list(edge.supporting_groups),
                crosses_best_cut=edge.crosses_best_cut,
            )
            for edge in value.edges
        ],
    )


def audit_visualization_artifact_view(lookup) -> AuditVisualizationArtifactView:
    artifact = lookup.audit_artifact
    return AuditVisualizationArtifactView(
        snapshot_id=lookup.snapshot_id,
        snapshot_version=lookup.snapshot_version,
        chain_id=lookup.chain_id,
        audit_artifact_id=artifact.artifact_id if artifact is not None else None,
        audit_artifact_fingerprint=(
            artifact.artifact_fingerprint if artifact is not None else None
        ),
        visualization=audit_visualization_view(lookup.visualization),
    )


def _metric_value_view(value):
    return {
        "availability": _status(value.availability),
        "value": value.value,
        "reason": value.reason,
    }


def _metric_vector_view(vector):
    if vector is None:
        return None
    return {
        name: _metric_value_view(getattr(vector, name))
        for name in (
            "weak_member_count",
            "minimum_membership_support",
            "evidence_union_coverage",
            "component_count",
            "audit_conductance",
            "audit_verdict_severity",
            "eligible_external_contradiction_count",
        )
    }


def _merge_evidence_view(evidence):
    """Keep live and restart-loaded Review payloads structurally identical."""
    if evidence is None:
        return None
    if isinstance(evidence, dict):
        if "cross_available_counts_by_group" in evidence:
            return evidence
        groups = evidence.get("groups") or ()
        return {
            "cross_pair_count": evidence.get("cross_pair_count"),
            "cross_available_counts_by_group": [
                {
                    "derivation_tag": (group.get("key") or {}).get("derivation_tag"),
                    "provenance_class": (group.get("key") or {}).get("provenance_class"),
                    "available_count": group.get("available_count"),
                    "support_count": group.get("support_count"),
                    "cross_fit": (
                        group["support_count"] / group["available_count"]
                        if group.get("available_count", 0) > 0
                        else None
                    ),
                }
                for group in groups
            ],
            "cross_audit_edge_count": evidence.get("cross_audit_edge_count"),
            "cross_audit_edge_coverage": (
                evidence["cross_audit_edge_count"] / evidence["cross_pair_count"]
                if evidence.get("cross_pair_count", 0) > 0
                else 0.0
            ),
            "cross_supported_group_count": sum(
                group.get("support_count", 0) > 0 for group in groups
            ),
            "cross_evidence_union_coverage": (
                evidence.get("cross_evidence_union_pair_count", 0)
                / evidence["cross_pair_count"]
                if evidence.get("cross_pair_count", 0) > 0
                else 0.0
            ),
        }
    return evidence.as_payload()


def _candidate_view(evaluation):
    candidate = evaluation.candidate
    merge_evidence = candidate.merge_evidence
    return {
        "candidate_id": candidate.candidate_id,
        "operation": candidate.operation.value,
        "member_ids": list(candidate.member_ids),
        "source_chain_id": candidate.source_chain_id,
        "target_chain_id": candidate.target_chain_id,
        "merged_chain_ids": list(candidate.merged_chain_ids)
        if candidate.merged_chain_ids is not None
        else None,
        "merge_evidence": _merge_evidence_view(merge_evidence),
        "source_ref": candidate.source_ref,
        "status": evaluation.status.value,
        "reason": evaluation.reason,
        "edit_cost": asdict(candidate.edit_cost),
        "partition_delta": {
            "before": [
                (chain_id, list(members))
                for chain_id, members in candidate.partition_delta.before
            ],
            "after": [
                (chain_id, list(members))
                for chain_id, members in candidate.partition_delta.after
            ],
        },
        "before": _metric_vector_view(evaluation.before),
        "after": _metric_vector_view(evaluation.after),
        "materially_improved_metrics": list(
            evaluation.materially_improved_metrics
        ),
        "move_structural_facts": (
            asdict(evaluation.move_structural_facts)
            if evaluation.move_structural_facts is not None
            else None
        ),
        "semantic_effects": [effect.value for effect in evaluation.semantic_effects],
    }


def _operation_view(operation):
    return {
        "operation": operation.operation.value,
        "status": operation.status.value,
        "reason": operation.reason,
        "search_mode": operation.search_mode.value,
        "discovered_candidate_count": operation.discovered_candidate_count,
        "evaluated_candidate_count": operation.evaluated_candidate_count,
        "rejected_candidate_count": operation.rejected_candidate_count,
        "candidate_limit": operation.candidate_limit,
        "candidates": [_candidate_view(item) for item in operation.candidates],
    }


def counterfactual_result_view(result):
    return {
        "identity": asdict(result.identity),
        "status": result.status.value,
        "reason": result.reason,
        "recommendation_status": result.recommendation_status.value,
        "remove": _operation_view(result.remove),
        "split": _operation_view(result.split),
        "move": _operation_view(result.move),
        "merge": _operation_view(result.merge),
        "recommendations": [
            _candidate_view(item) for item in result.recommendations
        ],
        "frontier_count_before_limit": result.frontier_count_before_limit,
        "frontier_truncated": result.frontier_truncated,
        "parameter_provenance": dict(result.parameter_provenance),
    }


def _enrich_candidates_with_learning_audit(
    result_dict: dict[str, Any] | None,
    job_id: str | None,
    job_view: Any,
    package: IngestedPackage | None,
    review_learning: Any | None,
) -> None:
    if not result_dict or not isinstance(result_dict, dict) or review_learning is None or not job_id:
        return
    candidates = result_dict.get("evaluated_candidates")
    if not candidates or not isinstance(candidates, list):
        return

    rev_id = review_learning.get_review_id_for_job(job_id)
    exps = review_learning._exposures.get(rev_id)
    if not exps:
        try:
            _, exps = review_learning.prepare_review_bundle(
                job_id=job_id,
                job_view=job_view,
                package=package,
            )
            review_learning._exposures[rev_id] = exps
        except Exception:
            exps = None

    if exps:
        exp_by_id = {exp.candidate_id: exp for exp in exps}
        for cand in candidates:
            if isinstance(cand, dict) and cand.get("candidate_id") in exp_by_id:
                exp = exp_by_id[cand["candidate_id"]]
                audit = (
                    exp.deterministic_context.get("ranking_audit")
                    or (exp.feature_payload or {}).get("ranking_audit")
                )
                if audit:
                    cand["ranking_audit"] = audit
                cand["displayed_rank"] = exp.displayed_rank

        if any(isinstance(c, dict) and c.get("displayed_rank") is not None for c in candidates):
            def sort_key(candidate: Any) -> tuple[bool, int]:
                if not isinstance(candidate, dict):
                    return (True, 999)
                gate = candidate.get("hard_gate_result") or {}
                eligible = str(gate.get("status", "")).upper() == "PASSED"
                return (not eligible, int(candidate.get("displayed_rank", 999)))
            candidates.sort(key=sort_key)


def counterfactual_job_view(
    job,
    package: IngestedPackage | None = None,
    language: str = "vi",
    review_learning: Any | None = None,
) -> CounterfactualJobView:
    def _iso(val):
        if val is None:
            return None
        return val.isoformat() if hasattr(val, "isoformat") else str(val)

    if isinstance(job, DomainCounterfactualJobView):
        payload = {
            "job_id": job.job_id,
            "chain_id": job.chain_id,
            "status": job.status.value,
            "progress_percent": job.progress_percent,
            "cache_hit": job.cache_hit,
            "cache_fingerprint": job.cache_fingerprint,
            "lineage_component_id": job.lineage_component_id,
            "submitted_at": _iso(job.submitted_at),
            "started_at": _iso(job.started_at),
            "completed_at": _iso(job.completed_at),
            "identity": asdict(job.identity),
            "result": (
                public_review_result(job.result, package=package, language=language)
                if job.result is not None
                else None
            ),
            "error": job.error,
        }
    else:
        def _get(key, default=None):
            if isinstance(job, dict):
                return job.get(key, default)
            val = getattr(job, key, default)
            return default if val is None else val

        res = _get("result")
        if res is not None:
            if hasattr(res, "recommendations"):
                res = public_review_result(res, package=package, language=language)
            elif isinstance(res, dict) and "evaluated_candidates" in res:
                candidates = res.get("evaluated_candidates", [])
                for cand in candidates:
                    if isinstance(cand, dict) and "comparative_explanation" not in cand:
                        from tier2.counterfactual.comparative_explainer import (
                            build_deterministic_comparative_explanation,
                        )
                        cand["comparative_explanation"] = build_deterministic_comparative_explanation(
                            operation=cand.get("operation", "UNKNOWN"),
                            candidate_id=cand.get("candidate_id", ""),
                            partition_delta=cand.get("partition_delta"),
                            before_metrics=cand.get("before_metrics") or cand.get("before"),
                            after_metrics=cand.get("after_metrics") or cand.get("after"),
                            metric_deltas=cand.get("metric_deltas"),
                            package=package,
                            member_ids=cand.get("member_ids", ()),
                            source_chain_id=cand.get("source_chain_id"),
                            target_chain_id=cand.get("target_chain_id"),
                            merged_chain_ids=cand.get("merged_chain_ids"),
                            operation_evidence=cand.get("operation_specific_evidence"),
                            language=language,
                        ).as_dict()

        payload = {
            "job_id": _get("job_id"),
            "chain_id": _get("chain_id"),
            "status": _get("status"),
            "progress_percent": _get("progress_percent"),
            "cache_hit": _get("cache_hit", False),
            "cache_fingerprint": _get("cache_fingerprint"),
            "lineage_component_id": _get("lineage_component_id"),
            "submitted_at": _iso(_get("submitted_at")),
            "started_at": _iso(_get("started_at")),
            "completed_at": _iso(_get("completed_at")),
            "identity": _get("identity"),
            "result": res,
            "error": _get("error"),
        }
    _enrich_candidates_with_learning_audit(
        payload.get("result"), payload.get("job_id"), job, package, review_learning
    )
    return CounterfactualJobView.model_validate(payload)


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
    unavailable = {str(item).upper() for item in analysis.graybox.unavailable_capabilities}
    def availability(name: str, tokens: tuple[str, ...], *, fail_closed: bool = False) -> dict[str, str | None]:
        if fail_closed:
            return {"state": "UNAVAILABLE", "reason": "No frozen historical model is attached to this chain-analysis response."}
        reason = next((item for item in unavailable if any(token in item for token in tokens)), None)
        return {"state": "UNAVAILABLE", "reason": reason} if reason else {"state": "AVAILABLE", "reason": None}
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
                        unavailable_reasons={
                            fit.channel_id: fit.unavailable_reason
                            for fit in group.channel_fits
                            if fit.unavailable_reason is not None
                        },
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
        evidence_availability={
            "historical": availability("historical", ("HISTORICAL",), fail_closed=True),
            "temporal_delay": availability("temporal_delay", ("DELAY", "TEMPORAL")),
            "topology": availability("topology", ("TOPOLOGY",)),
            "dependency": availability("dependency", ("DEPENDENCY",)),
        },
        descriptors=[
            descriptor_view(item)
            for item in (*analysis.descriptors.identity, *analysis.descriptors.contrastive)
        ],
        members=members,
        role_counts=analysis.role_counts(),
        phase_durations=analysis.phase_durations,
    )


def evolution_view(result) -> EvolutionView:
    """Stable HTTP projection of an already-persisted lineage artifact."""
    return EvolutionView(
        status=result.status,
        reason=result.reason,
        source_kind=result.source_kind,
        sequence_status=result.sequence_status,
        production_validation=result.production_validation,
        lineage_component_id=result.lineage_component_id,
        branch_id=result.branch_id,
        snapshot_id=result.snapshot_id,
        snapshot_version=result.snapshot_version,
        chain_id=result.chain_id,
        nodes=[
            {
                "snapshot_id": node.snapshot_id,
                "snapshot_version": node.snapshot_version,
                "chain_id": node.chain_id,
                "snapshot_time": node.snapshot_time.isoformat(),
                "lineage_component_id": node.lineage_component_id,
                "branch_id": node.branch_id,
                "source_kind": node.source_kind,
            }
            for node in result.nodes
        ],
        edges=[
            {
                "parent_snapshot_id": edge.parent_snapshot_id,
                "parent_snapshot_version": edge.parent_snapshot_version,
                "parent_chain_id": edge.parent_chain_id,
                "child_snapshot_id": edge.child_snapshot_id,
                "child_snapshot_version": edge.child_snapshot_version,
                "child_chain_id": edge.child_chain_id,
                "event_type": edge.event_type,
                "overlap_count": edge.overlap_count,
                "contain_parent": edge.contain_parent,
                "contain_child": edge.contain_child,
            }
            for edge in result.edges
        ],
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
        source_id=value.source_id,
        source_version=value.source_version,
        scenario_id=value.scenario_id,
        generator_version=value.generator_version,
        evidence_metadata=value.evidence_metadata,
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
        audit_visualization=audit_visualization_view(result.audit_visualization),
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
        topology_hypotheses=topology_hypotheses_view(result.topology_hypotheses),
        evidence_attribution=evidence_attribution_view(result.evidence_attribution),
        evidence_attribution_evaluation=attribution_evaluation_view(
            result.evidence_attribution_evaluation
        ),
    )


def evidence_attribution_view(result) -> EvidenceCoverageAttributionView:
    return EvidenceCoverageAttributionView(
        status=_status(result.status),
        mode=_status(result.mode),
        reason=_reason(result.reason),
        detail=result.detail,
        chain_size=result.chain_size,
        exact_max_members=result.exact_max_members,
        total_pair_count=result.total_pair_count,
        covered_pair_count=result.covered_pair_count,
        total_coverage=result.total_coverage,
        contributions=[
            {
                "group_id": item.group_id,
                "derivation_tag": item.derivation_tag,
                "provenance_class": _status(item.provenance_class),
                "explain_eligible": item.explain_eligible,
                "role_eligible": item.role_eligible,
                "audit_eligible": item.audit_eligible,
                "behavioral": item.behavioral,
                "supported_pair_count": item.supported_pair_count,
                "attribution": item.attribution,
            }
            for item in result.contributions
        ],
    )


def attribution_evaluation_view(result):
    return {
        "status": _status(result.status),
        "mode": _status(result.mode),
        "reason": _reason(result.reason),
        "group_count": result.group_count,
        "primary": {
            "ordering": list(result.primary.ordering),
            "coverage_curve": list(result.primary.coverage_curve),
            "auc": result.primary.auc,
        },
        "reverse": {
            "ordering": list(result.reverse.ordering),
            "coverage_curve": list(result.reverse.coverage_curve),
            "auc": result.reverse.auc,
        },
        "random": {
            "algorithm": result.random.algorithm,
            "seed": result.random.seed,
            "repetitions": result.random.repetitions,
            "repetitions_executed": result.random.repetitions_executed,
            "mean_curve": list(result.random.mean_curve),
            "std_curve": list(result.random.std_curve),
            "mean_auc": result.random.mean_auc,
            "std_auc": result.random.std_auc,
        },
        "delta_vs_random_auc": result.delta_vs_random_auc,
        "delta_vs_reverse_auc": result.delta_vs_reverse_auc,
    }


def _status(value) -> str:
    return value.value if hasattr(value, "value") else value


def _reason(value) -> str | None:
    return value.value if hasattr(value, "value") else value


def dominator_view(result: DominatorResult) -> DominatorView:
    """Project the annotation without introducing an evidence score."""
    return DominatorView(
        status=_status(result.status),
        reason=_reason(result.reason),
        semantic=result.semantic,
        witness_resource_id=result.witness_resource_id,
        covered_resource_ids=list(result.covered_resource_ids),
        source_ref=result.source_ref,
        source_id=result.source_id,
        source_version=result.source_version,
        scenario_id=result.scenario_id,
        generator_version=result.generator_version,
        relation_type=result.relation_type,
        provenance_class=_status(result.provenance_class),
        provenance_subtype=_status(result.provenance_subtype),
        source_kind=result.source_kind,
    )


def propagation_view(result: PropagationResult) -> PropagationView:
    return PropagationView(
        status=_status(result.status),
        reason=_reason(result.reason),
        semantic=result.semantic,
        source_ref=result.source_ref,
        source_id=result.source_id,
        source_version=result.source_version,
        scenario_id=result.scenario_id,
        generator_version=result.generator_version,
        relation_type=result.relation_type,
        provenance_class=_status(result.provenance_class),
        provenance_subtype=_status(result.provenance_subtype),
        source_kind=result.source_kind,
        config_version=result.config_version,
        parameter_provenance=dict(result.parameter_provenance),
        diagnostics=PropagationDiagnosticsView(
            candidate_node_count=result.candidate_node_count,
            candidate_edge_count=result.candidate_edge_count,
            iterations=result.iterations,
            final_l1_distance=result.final_l1_distance,
            convergence_tolerance=result.convergence_tolerance,
            restart_probability=result.restart_probability,
            seed_policy=result.seed_policy,
            dangling_policy=result.dangling_policy,
            config_version=result.config_version,
            parameter_provenance=dict(result.parameter_provenance),
        ),
        node_scores=[
            PropagationNodeScoreView(alarm_id=item.alarm_id, score=item.score)
            for item in result.node_scores
        ],
        hypotheses=[
            PropagationEdgeHypothesisView(
                source_alarm_id=item.source_alarm_id,
                target_alarm_id=item.target_alarm_id,
                score=item.score,
                transition_probability=item.transition_probability,
                temporal_delta_seconds=item.temporal_delta_seconds,
            )
            for item in result.hypotheses
        ],
    )


def resource_details_view(result: ResourceDetails) -> ResourceDetailsView:
    details_available = _status(result.status) == "AVAILABLE"
    return ResourceDetailsView(
        status=_status(result.status),
        reason=_reason(result.reason),
        missing_resources=(
            list(result.missing_resources)
            if details_available and result.missing_resources is not None
            else None
        ),
        extra_resources=(
            list(result.extra_resources)
            if details_available and result.extra_resources is not None
            else None
        ),
    )


def dependency_scope_view(result: DependencyScopeResult) -> DependencyScopeView:
    return DependencyScopeView(
        status=_status(result.status),
        reason=_reason(result.reason),
        semantic=result.semantic,
        witness_resource_id=result.witness_resource_id,
        source_ref=result.source_ref,
        source_id=result.source_id,
        source_version=result.source_version,
        scenario_id=result.scenario_id,
        generator_version=result.generator_version,
        relation_type=result.relation_type,
        provenance_class=_status(result.provenance_class),
        provenance_subtype=_status(result.provenance_subtype),
        source_kind=result.source_kind,
        observed_resource_count=result.observed_resource_count,
        scope_resource_count=result.scope_resource_count,
        intersection_count=result.intersection_count,
        union_count=result.union_count,
        observed_coverage=result.observed_coverage,
        scope_precision=result.scope_precision,
        jaccard=result.jaccard,
        missing_resource_count=result.missing_resource_count,
        extra_resource_count=result.extra_resource_count,
        max_scope_resources=result.max_scope_resources,
        max_materialized_resources=result.max_materialized_resources,
        parameter_provenance=dict(result.parameter_provenance),
        resource_details=resource_details_view(result.resource_details),
    )


def topology_hypotheses_view(
    result: TopologyHypothesesResult,
) -> TopologyHypothesesView:
    return TopologyHypothesesView(
        dominator=dominator_view(result.dominator),
        propagation=propagation_view(result.propagation),
        dependency_scope=dependency_scope_view(result.dependency_scope),
    )


def job_view(view: Tier2JobView) -> JobView:
    if isinstance(view, Tier2JobView):
        payload = {
            "job_id": view.job_id,
            "chain_id": view.chain_id,
            "status": view.status.value,
            "progress_percent": view.progress_percent,
            "cache_hit": view.cache_hit,
            "result": (
                deep_dive_view(view.result).model_dump(mode="json")
                if view.result is not None
                else None
            ),
            "error": view.error,
        }
    else:
        payload = {
            "job_id": view.job_id,
            "chain_id": view.chain_id,
            "status": view.status,
            "progress_percent": view.progress_percent,
            "cache_hit": view.cache_hit,
            "result": view.result,
            "error": view.error,
        }
    return JobView.model_validate(payload)


def operator_feedback_view(feedback: Any) -> OperatorFeedbackView:
    if is_dataclass(feedback):
        d = asdict(feedback)
    elif hasattr(feedback, "__dict__") and not isinstance(feedback, dict):
        d = dict(feedback.__dict__)
    else:
        d = dict(feedback)
    created_at = d.get("created_at")
    if isinstance(created_at, datetime):
        created_at = created_at.isoformat()
    decision_val = d["decision"]
    if hasattr(decision_val, "value"):
        decision_val = decision_val.value
    truth_tier_val = d.get("truth_tier", "PO_ASSERTED")
    if hasattr(truth_tier_val, "value"):
        truth_tier_val = truth_tier_val.value

    return OperatorFeedbackView(
        feedback_id=d["feedback_id"],
        job_id=d.get("job_id", ""),
        snapshot_id=d.get("snapshot_id", ""),
        snapshot_version=d.get("snapshot_version", ""),
        chain_id=d.get("chain_id", ""),
        candidate_id=d.get("candidate_id"),
        operation=d.get("operation", ""),
        decision=str(decision_val),
        operator_id=d.get("reviewer_subject") or d.get("operator_id", ""),
        confidence=d.get("confidence"),
        reviewer_subject=d.get("reviewer_subject"),
        reviewer_role=d.get("reviewer_role"),
        domain_scope=list(d.get("domain_scope") or []),
        truth_tier=str(truth_tier_val),
        supersedes_feedback_id=d.get("supersedes_feedback_id"),
        reason=d.get("reason_text") or d.get("reason"),
        reason_policy_version=d.get("reason_policy_version"),
        reason_codes=list(d.get("reason_codes") or []),
        partition_delta=d.get("partition_delta", {}),
        has_manual_correction=bool(d.get("has_manual_correction") or d.get("manual_correction") or str(decision_val) == "MANUAL_CORRECTION"),
        created_at=str(created_at),
    )


def ai_suggestion_view(result: Any) -> AISuggestionView:
    if hasattr(result, "to_dict"):
        d = result.to_dict()
    elif is_dataclass(result):
        d = asdict(result)
    else:
        d = dict(result)
    return AISuggestionView(
        chain_id=d["chain_id"],
        status=d["status"],
        model=d["model"],
        narrative=d["narrative"],
        grounded_claims=list(d.get("grounded_claims", [])),
        disclaimer=d["disclaimer"],
        provider_status=d.get("provider_status"),
        review_status=d.get("review_status", "NOT_AVAILABLE"),
        review_reason=d.get("review_reason"),
    )
