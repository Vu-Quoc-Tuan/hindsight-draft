"""Fail-closed loader for the versioned analysis parameter registry.

Low-level algorithms remain file-system independent: this module translates one
validated YAML artifact into their explicit dataclass inputs.  Every scalar
retains its source category so explanations and benchmark reports can expose
parameter provenance instead of anonymous literals (ADR-0025).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from pathlib import Path
from typing import Any, Iterable

import yaml

from descriptor import MiningConfig
from groups import RoleThresholds
from similar_chains import CorpusPolicy, ModelUpdatePolicy


class AnalysisConfigError(ValueError):
    """Raised when analysis configuration is missing or semantically invalid."""


class ParameterSource(str, Enum):
    SYSTEM_PROVIDED = "SYSTEM_PROVIDED"
    DATA_DRIVEN = "DATA_DRIVEN"
    DOCUMENTED_DEFAULT = "DOCUMENTED_DEFAULT"
    FROZEN_SPEC = "FROZEN_SPEC"


class IncrementalSnapshotMode(str, Enum):
    DISABLED = "disabled"


class ChunkRetentionMode(str, Enum):
    """Durable ingest-artifact retention policy."""

    KEEP = "KEEP"
    DELETE_AFTER_READY = "DELETE_AFTER_READY"


class CalibrationStatus(str, Enum):
    SYNTHETIC_ONLY = "SYNTHETIC_ONLY"
    PRODUCTION_CALIBRATED = "PRODUCTION_CALIBRATED"


@dataclass(frozen=True)
class IncrementalSnapshotPolicy:
    mode: IncrementalSnapshotMode
    reason: str

    @property
    def enabled(self) -> bool:
        return False


@dataclass(frozen=True)
class ChunkRetentionPolicy:
    mode: ChunkRetentionMode


@dataclass(frozen=True)
class SimilarChainsPolicy:
    corpus_policy: CorpusPolicy
    model_update_policy: ModelUpdatePolicy
    temporal_cutoff: str
    exclude_same_lineage: bool


@dataclass(frozen=True)
class HistoricalEvidencePolicy:
    """Optional until an explicit, versioned lift cap is supplied."""

    min_support: ConfiguredValue
    lambda_h: ConfiguredValue
    lift_cap: ConfiguredValue


@dataclass(frozen=True)
class TemporalDelayPolicy:
    min_relation_episodes: ConfiguredValue
    model_selection_min_episodes: ConfiguredValue
    validation_fraction: ConfiguredValue
    model_selection_seed: ConfiguredValue
    local_mass_halfwidth_candidates_seconds: tuple[float, ...]
    histogram_bin_width_candidates_seconds: tuple[float, ...]
    kde_bandwidth_candidates_seconds: tuple[float, ...]
    fallback_model: str
    fallback_local_mass_halfwidth_seconds: float
    fallback_histogram_bin_width_seconds: float | None
    fallback_kde_bandwidth_seconds: float | None
    support_threshold: ConfiguredValue


@dataclass(frozen=True)
class ConfiguredValue:
    path: str
    value: int | float
    source: ParameterSource


@dataclass(frozen=True)
class AttributionEvaluationConfig:
    """Versioned deterministic-randomization envelope for ADR-0031 evaluation."""

    randomization_algorithm: str
    random_seed: ConfiguredValue
    random_repetitions: ConfiguredValue


@dataclass(frozen=True)
class CounterfactualConfig:
    config_version: str
    calibration_status: CalibrationStatus
    max_chain_members: int
    max_remove_candidates: int
    max_split_candidates: int
    max_recommendations: int
    membership_support_below: float
    representativeness_below: float
    adverse_margin_below: float
    minimum_membership_improvement: float
    minimum_coverage_improvement: float
    minimum_conductance_improvement: float
    pareto_tolerance: float
    max_move_candidates: int | None = None
    move_reason: str | None = None
    max_merge_candidates: int | None = None
    merge_reason: str | None = None


@dataclass(frozen=True)
class PropagationConfig:
    config_version: str
    restart_probability: ConfiguredValue
    convergence_tolerance: ConfiguredValue
    max_iterations: ConfiguredValue
    decay_type: str
    decay_parameter: ConfiguredValue
    score_threshold: ConfiguredValue
    max_candidate_edges: ConfiguredValue


@dataclass(frozen=True)
class DependencyScopeConfig:
    max_scope_resources: ConfiguredValue
    max_materialized_resources: ConfiguredValue


@dataclass(frozen=True)
class P2TopologyConfig:
    propagation: PropagationConfig | None
    propagation_reason: str | None
    dependency_scope: DependencyScopeConfig | None
    dependency_scope_reason: str | None


@dataclass(frozen=True)
class _ParameterRule:
    numeric_type: type[int] | type[float]
    minimum: float | None = None
    maximum: float | None = None
    inclusive_minimum: bool = True
    inclusive_maximum: bool = True

    def validate(self, path: str, value: Any) -> int | float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise AnalysisConfigError(f"{path}: value must be numeric")
        if self.numeric_type is int and not isinstance(value, int):
            raise AnalysisConfigError(f"{path}: value must be an integer")
        try:
            normalized: int | float = (
                int(value) if self.numeric_type is int else float(value)
            )
        except OverflowError as exc:
            raise AnalysisConfigError(f"{path}: value is out of range") from exc
        if self.minimum is not None:
            invalid = (
                normalized < self.minimum
                if self.inclusive_minimum
                else normalized <= self.minimum
            )
            if invalid:
                operator = ">=" if self.inclusive_minimum else ">"
                raise AnalysisConfigError(
                    f"{path}: value must be {operator} {self.minimum}"
                )
        if self.maximum is not None:
            invalid = (
                normalized > self.maximum
                if self.inclusive_maximum
                else normalized >= self.maximum
            )
            if invalid:
                operator = "<=" if self.inclusive_maximum else "<"
                raise AnalysisConfigError(
                    f"{path}: value must be {operator} {self.maximum}"
                )
        return normalized


_PROBABILITY = _ParameterRule(float, 0.0, 1.0)
_STRICT_PROBABILITY = _ParameterRule(
    float, 0.0, 1.0, inclusive_minimum=False, inclusive_maximum=False
)
_BALANCE_RATIO = _ParameterRule(float, 0.0, 0.5)
_POSITIVE_FLOAT = _ParameterRule(float, 0.0, inclusive_minimum=False)
_POSITIVE_INT = _ParameterRule(int, 0, inclusive_minimum=False)
_NONNEGATIVE_INT = _ParameterRule(int, 0)

_P2_PROPAGATION_RULES: dict[str, _ParameterRule] = {
    "rwr.restart_probability": _STRICT_PROBABILITY,
    "rwr.convergence_tolerance": _POSITIVE_FLOAT,
    "rwr.max_iterations": _POSITIVE_INT,
    "temporal.decay_parameter": _POSITIVE_FLOAT,
    "acceptance.score_threshold": _PROBABILITY,
    "limits.max_candidate_edges": _POSITIVE_INT,
}

_P2_DEPENDENCY_SCOPE_RULES: dict[str, _ParameterRule] = {
    "limits.max_scope_resources": _POSITIVE_INT,
    "limits.max_materialized_resources": _POSITIVE_INT,
}

ATTRIBUTION_RANDOMIZATION_ALGORITHM = "SPLITMIX64_FISHER_YATES_V1"


PARAMETER_RULES: dict[str, _ParameterRule] = {
    "temporal.burst.gap_seconds": _POSITIVE_INT,
    "temporal.delay.bandwidth_seconds": _POSITIVE_FLOAT,
    "temporal.delay.support_threshold": _PROBABILITY,
    "dependency.max_hop": _POSITIVE_INT,
    "dependency.lambda_dep": _POSITIVE_FLOAT,
    "dependency.common_support_threshold": _PROBABILITY,
    "history.min_support": _POSITIVE_INT,
    "history.lambda_h": _POSITIVE_FLOAT,
    "role.c_min": _PROBABILITY,
    "role.min_computable_groups": _POSITIVE_INT,
    "role.s_min": _PROBABILITY,
    "role.s_weak": _PROBABILITY,
    "role.r_min": _PROBABILITY,
    "role.core_quantile": _PROBABILITY,
    "role.small_chain_threshold": _POSITIVE_INT,
    "descriptor.max_depth": _POSITIVE_INT,
    "descriptor.beam_width": _POSITIVE_INT,
    "descriptor.top_k": _POSITIVE_INT,
    "descriptor.max_values_per_field": _POSITIVE_INT,
    "descriptor.precision_global_min": _PROBABILITY,
    "descriptor.precision_local_min": _PROBABILITY,
    "descriptor.redundancy_jaccard": _PROBABILITY,
    "contrastive.local_universe_k": _POSITIVE_INT,
    "contrastive.top_k": _POSITIVE_INT,
    "contrastive.g_min": _POSITIVE_INT,
    "redundancy.small_dt_seconds": _NONNEGATIVE_INT,
    "audit.rho": _BALANCE_RATIO,
    "audit.min_side_size": _POSITIVE_INT,
    "audit.small_chain_threshold": _POSITIVE_INT,
    "audit.calibration_n_min": _POSITIVE_INT,
    "audit.calibration_quantile": _PROBABILITY,
    "audit.global_weak_baseline": _PROBABILITY,
    "audit.exact_max_members": _POSITIVE_INT,
    "lineage.min_intersection": _POSITIVE_INT,
    "lineage.beta_parent": _PROBABILITY,
    "lineage.beta_child": _PROBABILITY,
    "lineage.small_chain_jaccard": _PROBABILITY,
    "lineage.stable_threshold": _PROBABILITY,
    "lineage.boundary_threshold": _PROBABILITY,
    "similar_chains.top_descriptor_predicates": _POSITIVE_INT,
    "similar_chains.result_top_k": _POSITIVE_INT,
}


@dataclass(frozen=True)
class AnalysisConfig:
    config_version: str
    status: str
    parameters: dict[str, ConfiguredValue]
    incremental_snapshot: IncrementalSnapshotPolicy
    chunk_retention: ChunkRetentionPolicy
    similar_chains: SimilarChainsPolicy
    historical_evidence: HistoricalEvidencePolicy | None
    historical_evidence_reason: str | None
    temporal_delay: TemporalDelayPolicy | None
    temporal_delay_reason: str | None
    p2_topology: P2TopologyConfig
    attribution_evaluation: AttributionEvaluationConfig | None = None
    attribution_evaluation_reason: str | None = None
    counterfactual: CounterfactualConfig | None = None
    counterfactual_reason: str | None = None

    REQUIRED_PARAMETERS = tuple(PARAMETER_RULES)

    def parameter(self, path: str) -> ConfiguredValue:
        try:
            return self.parameters[path]
        except KeyError as exc:
            raise AnalysisConfigError(f"unknown parameter {path!r}") from exc

    def value(self, path: str) -> int | float:
        return self.parameter(path).value

    def role_thresholds(self) -> RoleThresholds:
        return RoleThresholds(
            config_version=self.config_version,
            s_min=float(self.value("role.s_min")),
            s_weak=float(self.value("role.s_weak")),
            c_min=float(self.value("role.c_min")),
            r_min=float(self.value("role.r_min")),
            core_quantile=float(self.value("role.core_quantile")),
            min_computable_groups=int(self.value("role.min_computable_groups")),
            small_chain_threshold=int(self.value("role.small_chain_threshold")),
        )

    def mining_config(self) -> MiningConfig:
        return MiningConfig(
            config_version=self.config_version,
            max_depth=int(self.value("descriptor.max_depth")),
            beam_width=int(self.value("descriptor.beam_width")),
            top_k=int(self.value("descriptor.top_k")),
            precision_global_min=float(self.value("descriptor.precision_global_min")),
            precision_local_min=float(self.value("descriptor.precision_local_min")),
            redundancy_jaccard=float(self.value("descriptor.redundancy_jaccard")),
        )


def _lookup(document: dict[str, Any], path: str) -> Any:
    current: Any = document
    for segment in path.split("."):
        if not isinstance(current, dict) or segment not in current:
            raise AnalysisConfigError(f"missing required parameter {path!r}")
        current = current[segment]
    return current


def _load_p2_configured_value(
    document: dict[str, Any],
    path: str,
    rule: _ParameterRule,
    *,
    configured_path: str,
) -> ConfiguredValue:
    raw = _lookup(document, path)
    if not isinstance(raw, dict):
        raise AnalysisConfigError(f"{path}: expected mapping with value and source")
    if "value" not in raw:
        raise AnalysisConfigError(f"{path}: missing value")
    if "source" not in raw:
        raise AnalysisConfigError(f"{path}: missing source")
    try:
        source = ParameterSource(raw["source"])
    except (TypeError, ValueError) as exc:
        raise AnalysisConfigError(
            f"{path}: unknown parameter source {raw['source']!r}"
        ) from exc
    value = rule.validate(path, raw["value"])
    if isinstance(value, float) and not isfinite(value):
        raise AnalysisConfigError(f"{path}: value must be finite")
    return ConfiguredValue(
        path=configured_path,
        value=value,
        source=source,
    )


def _load_propagation_config(document: dict[str, Any]) -> PropagationConfig:
    raw_config_version = _lookup(document, "config_version")
    if not isinstance(raw_config_version, str) or not raw_config_version.strip():
        raise AnalysisConfigError(
            "propagation.config_version must be a non-empty string"
        )
    raw_decay_type = _lookup(document, "temporal.decay_type")
    if raw_decay_type != "exponential":
        raise AnalysisConfigError(
            "propagation.temporal.decay_type must be exponential"
        )
    values = {
        path: _load_p2_configured_value(
            document, path, rule, configured_path=f"propagation.{path}"
        )
        for path, rule in _P2_PROPAGATION_RULES.items()
    }
    return PropagationConfig(
        config_version=raw_config_version.strip(),
        restart_probability=values["rwr.restart_probability"],
        convergence_tolerance=values["rwr.convergence_tolerance"],
        max_iterations=values["rwr.max_iterations"],
        decay_type="exponential",
        decay_parameter=values["temporal.decay_parameter"],
        score_threshold=values["acceptance.score_threshold"],
        max_candidate_edges=values["limits.max_candidate_edges"],
    )


def _load_dependency_scope_config(document: dict[str, Any]) -> DependencyScopeConfig:
    values = {
        path: _load_p2_configured_value(
            document, path, rule, configured_path=f"dependency_scope.{path}"
        )
        for path, rule in _P2_DEPENDENCY_SCOPE_RULES.items()
    }
    max_scope_resources = values["limits.max_scope_resources"]
    max_materialized_resources = values["limits.max_materialized_resources"]
    if max_materialized_resources.value > max_scope_resources.value:
        raise AnalysisConfigError(
            "dependency_scope.limits.max_materialized_resources must be <= "
            "max_scope_resources"
        )
    return DependencyScopeConfig(
        max_scope_resources=max_scope_resources,
        max_materialized_resources=max_materialized_resources,
    )


def _load_optional_p2_topology(document: dict[str, Any]) -> P2TopologyConfig:
    raw_propagation = document.get("propagation")
    try:
        if not isinstance(raw_propagation, dict):
            raise AnalysisConfigError("propagation must be a YAML mapping")
        propagation = _load_propagation_config(raw_propagation)
        propagation_reason = None
    except AnalysisConfigError:
        propagation = None
        propagation_reason = "PROPAGATION_CONFIG_INCOMPLETE"

    raw_dependency_scope = document.get("dependency_scope")
    try:
        if not isinstance(raw_dependency_scope, dict):
            raise AnalysisConfigError("dependency_scope must be a YAML mapping")
        dependency_scope = _load_dependency_scope_config(raw_dependency_scope)
        dependency_scope_reason = None
    except AnalysisConfigError:
        dependency_scope = None
        dependency_scope_reason = "DEPENDENCY_SCOPE_CONFIG_INCOMPLETE"

    return P2TopologyConfig(
        propagation=propagation,
        propagation_reason=propagation_reason,
        dependency_scope=dependency_scope,
        dependency_scope_reason=dependency_scope_reason,
    )


def _load_optional_attribution_evaluation(
    document: dict[str, Any],
) -> tuple[AttributionEvaluationConfig | None, str | None]:
    try:
        raw = _lookup(document, "attribution_evaluation.randomization")
        if not isinstance(raw, dict):
            raise AnalysisConfigError(
                "attribution_evaluation.randomization must be a YAML mapping"
            )
        algorithm = raw.get("algorithm")
        if algorithm != ATTRIBUTION_RANDOMIZATION_ALGORITHM:
            raise AnalysisConfigError(
                "attribution_evaluation.randomization.algorithm must be "
                f"{ATTRIBUTION_RANDOMIZATION_ALGORITHM}"
            )
        seed = _load_p2_configured_value(
            raw,
            "seed",
            _NONNEGATIVE_INT,
            configured_path="attribution_evaluation.randomization.seed",
        )
        repetitions = _load_p2_configured_value(
            raw,
            "repetitions",
            _POSITIVE_INT,
            configured_path="attribution_evaluation.randomization.repetitions",
        )
        return (
            AttributionEvaluationConfig(
                randomization_algorithm=algorithm,
                random_seed=seed,
                random_repetitions=repetitions,
            ),
            None,
        )
    except AnalysisConfigError:
        return None, "ATTRIBUTION_EVALUATION_CONFIG_INCOMPLETE"


def _load_optional_historical_evidence(
    document: dict[str, Any], parameters: dict[str, ConfiguredValue]
) -> tuple[HistoricalEvidencePolicy | None, str | None]:
    """Do not invent ``lift_cap`` merely because older configs lack it."""
    try:
        lift_cap = _load_p2_configured_value(
            document,
            "history.lift_cap",
            _ParameterRule(float, 1.0, inclusive_minimum=False),
            configured_path="history.lift_cap",
        )
        return (
            HistoricalEvidencePolicy(
                min_support=parameters["history.min_support"],
                lambda_h=parameters["history.lambda_h"],
                lift_cap=lift_cap,
            ),
            None,
        )
    except (AnalysisConfigError, KeyError):
        return None, "HISTORY_CONFIG_INCOMPLETE"


def _load_optional_temporal_delay(
    document: dict[str, Any], parameters: dict[str, ConfiguredValue]
) -> tuple[TemporalDelayPolicy | None, str | None]:
    try:
        raw = _lookup(document, "temporal.delay")
        if not isinstance(raw, dict):
            raise AnalysisConfigError("temporal.delay must be a YAML mapping")
        def scalar(name: str, rule: _ParameterRule) -> ConfiguredValue:
            return _load_p2_configured_value(raw, name, rule, configured_path=f"temporal.delay.{name}")
        def sequence(name: str) -> tuple[float, ...]:
            values = raw.get(name)
            if not isinstance(values, list) or not values or any(isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0 for v in values):
                raise AnalysisConfigError(f"temporal.delay.{name} must be non-empty positive numeric list")
            return tuple(float(v) for v in values)
        fallback_model = raw.get("fallback_model")
        if fallback_model not in {"HISTOGRAM", "GAUSSIAN_KDE"}:
            raise AnalysisConfigError("temporal.delay.fallback_model is required")
        fallback_halfwidth = raw.get("fallback_local_mass_halfwidth_seconds")
        if isinstance(fallback_halfwidth, bool) or not isinstance(fallback_halfwidth, (int, float)) or fallback_halfwidth <= 0:
            raise AnalysisConfigError("temporal.delay.fallback_local_mass_halfwidth_seconds is required")
        histogram, kde = raw.get("fallback_histogram_bin_width_seconds"), raw.get("fallback_kde_bandwidth_seconds")
        return TemporalDelayPolicy(
            scalar("min_relation_episodes", _POSITIVE_INT), scalar("model_selection_min_episodes", _POSITIVE_INT),
            scalar("validation_fraction", _STRICT_PROBABILITY), scalar("model_selection_seed", _NONNEGATIVE_INT),
            sequence("local_mass_halfwidth_candidates_seconds"), sequence("histogram_bin_width_candidates_seconds"), sequence("kde_bandwidth_candidates_seconds"),
            fallback_model, float(fallback_halfwidth),
            float(histogram) if isinstance(histogram, (int, float)) and not isinstance(histogram, bool) and histogram > 0 else None,
            float(kde) if isinstance(kde, (int, float)) and not isinstance(kde, bool) and kde > 0 else None,
            parameters["temporal.delay.support_threshold"],
        ), None
    except (AnalysisConfigError, KeyError):
        return None, "TEMPORAL_DELAY_CONFIG_INCOMPLETE"


def _counterfactual_number(
    document: dict[str, Any], path: str, rule: _ParameterRule
) -> int | float:
    value = rule.validate(f"counterfactual.{path}", _lookup(document, path))
    if isinstance(value, float) and not isfinite(value):
        raise AnalysisConfigError(f"counterfactual.{path}: value must be finite")
    return value


def _load_optional_counterfactual(
    document: dict[str, Any],
) -> tuple[CounterfactualConfig | None, str | None]:
    try:
        raw = document.get("counterfactual")
        if not isinstance(raw, dict):
            raise AnalysisConfigError("counterfactual must be a YAML mapping")
        raw_version = _lookup(raw, "config_version")
        if not isinstance(raw_version, str) or not raw_version.strip():
            raise AnalysisConfigError(
                "counterfactual.config_version must be a non-empty string"
            )
        try:
            calibration_status = CalibrationStatus(
                _lookup(raw, "calibration_status")
            )
        except (TypeError, ValueError) as exc:
            raise AnalysisConfigError(
                "counterfactual.calibration_status is invalid"
            ) from exc
        try:
            max_move_candidates = int(
                _counterfactual_number(raw, "move.max_candidates", _POSITIVE_INT)
            )
            move_reason = None
        except AnalysisConfigError:
            # MOVE is an independent P1 operation.  Omitting its envelope must
            # not disable the already-calibrated REMOVE/SPLIT P0 operations.
            max_move_candidates = None
            move_reason = "MOVE_POLICY_NOT_CALIBRATED"
        try:
            max_merge_candidates = int(
                _counterfactual_number(raw, "merge.max_candidates", _POSITIVE_INT)
            )
            merge_reason = None
        except AnalysisConfigError:
            max_merge_candidates = None
            merge_reason = "MERGE_POLICY_NOT_CALIBRATED"
        return (
            CounterfactualConfig(
                config_version=raw_version.strip(),
                calibration_status=calibration_status,
                max_chain_members=int(
                    _counterfactual_number(raw, "limits.max_chain_members", _POSITIVE_INT)
                ),
                max_remove_candidates=int(
                    _counterfactual_number(raw, "limits.max_remove_candidates", _POSITIVE_INT)
                ),
                max_split_candidates=int(
                    _counterfactual_number(raw, "limits.max_split_candidates", _POSITIVE_INT)
                ),
                max_recommendations=int(
                    _counterfactual_number(raw, "limits.max_recommendations", _POSITIVE_INT)
                ),
                membership_support_below=float(
                    _counterfactual_number(raw, "remove_triggers.membership_support_below", _PROBABILITY)
                ),
                representativeness_below=float(
                    _counterfactual_number(raw, "remove_triggers.representativeness_below", _PROBABILITY)
                ),
                adverse_margin_below=float(
                    _counterfactual_number(raw, "remove_triggers.adverse_margin_below", _ParameterRule(float))
                ),
                minimum_membership_improvement=float(
                    _counterfactual_number(raw, "improvement.minimum_membership_improvement", _ParameterRule(float, 0.0))
                ),
                minimum_coverage_improvement=float(
                    _counterfactual_number(raw, "improvement.minimum_coverage_improvement", _ParameterRule(float, 0.0))
                ),
                minimum_conductance_improvement=float(
                    _counterfactual_number(raw, "improvement.minimum_conductance_improvement", _ParameterRule(float, 0.0))
                ),
                pareto_tolerance=float(
                    _counterfactual_number(raw, "improvement.pareto_tolerance", _ParameterRule(float, 0.0))
                ),
                max_move_candidates=max_move_candidates,
                move_reason=move_reason,
                max_merge_candidates=max_merge_candidates,
                merge_reason=merge_reason,
            ),
            None,
        )
    except AnalysisConfigError:
        return None, "COUNTERFACTUAL_CONFIG_INCOMPLETE"


def _load_chunk_retention(document: dict[str, Any]) -> ChunkRetentionPolicy:
    """Load the deployment retention choice, keeping legacy YAML fail-safe."""
    raw_ingest = document.get("ingest")
    if raw_ingest is None:
        return ChunkRetentionPolicy(mode=ChunkRetentionMode.KEEP)
    if not isinstance(raw_ingest, dict):
        raise AnalysisConfigError("ingest must be a YAML mapping")
    raw_retention = raw_ingest.get("chunk_retention")
    if not isinstance(raw_retention, dict):
        raise AnalysisConfigError("ingest.chunk_retention must be a YAML mapping")
    try:
        mode = ChunkRetentionMode(raw_retention.get("mode"))
    except (TypeError, ValueError) as exc:
        raise AnalysisConfigError(
            "ingest.chunk_retention.mode must be KEEP or DELETE_AFTER_READY"
        ) from exc
    return ChunkRetentionPolicy(mode=mode)


def load_analysis_config(
    path: str | Path,
    *,
    required_parameters: Iterable[str] | None = None,
) -> AnalysisConfig:
    target = Path(path)
    try:
        document = yaml.safe_load(target.read_text(encoding="utf-8"))
    except OSError as exc:
        raise AnalysisConfigError(f"cannot read analysis config {target}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise AnalysisConfigError(f"invalid YAML in {target}: {exc}") from exc
    if not isinstance(document, dict):
        raise AnalysisConfigError("analysis config must be a YAML mapping")

    version = document.get("config_version")
    if not isinstance(version, str) or not version.strip():
        raise AnalysisConfigError("config_version must be a non-empty string")
    status = document.get("status", "unspecified")
    if not isinstance(status, str) or not status.strip():
        raise AnalysisConfigError("status must be a non-empty string when provided")

    requested = tuple(required_parameters or AnalysisConfig.REQUIRED_PARAMETERS)
    parameters: dict[str, ConfiguredValue] = {}
    for parameter_path in requested:
        rule = PARAMETER_RULES.get(parameter_path)
        if rule is None:
            raise AnalysisConfigError(f"no validation rule for {parameter_path!r}")
        raw = _lookup(document, parameter_path)
        if not isinstance(raw, dict):
            raise AnalysisConfigError(
                f"{parameter_path}: expected mapping with value and source"
            )
        if "value" not in raw:
            raise AnalysisConfigError(f"{parameter_path}: missing value")
        if "source" not in raw:
            raise AnalysisConfigError(f"{parameter_path}: missing source")
        try:
            source = ParameterSource(raw["source"])
        except (TypeError, ValueError) as exc:
            raise AnalysisConfigError(
                f"{parameter_path}: unknown parameter source {raw['source']!r}"
            ) from exc
        parameters[parameter_path] = ConfiguredValue(
            path=parameter_path,
            value=rule.validate(parameter_path, raw["value"]),
            source=source,
        )

    raw_incremental = document.get("incremental_snapshot")
    if not isinstance(raw_incremental, dict):
        raise AnalysisConfigError("incremental_snapshot must be a YAML mapping")
    raw_mode = raw_incremental.get("mode")
    if raw_mode != IncrementalSnapshotMode.DISABLED.value:
        raise AnalysisConfigError(
            "incremental_snapshot.mode only supports disabled until sequential "
            "production snapshots have benchmark evidence"
        )
    reason = raw_incremental.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise AnalysisConfigError(
            "incremental_snapshot.reason must be a non-empty string"
        )
    incremental_snapshot = IncrementalSnapshotPolicy(
        mode=IncrementalSnapshotMode.DISABLED,
        reason=reason.strip(),
    )
    chunk_retention = _load_chunk_retention(document)

    raw_similar = document.get("similar_chains")
    if not isinstance(raw_similar, dict):
        raise AnalysisConfigError("similar_chains must be a YAML mapping")
    try:
        corpus_policy = CorpusPolicy(raw_similar.get("corpus_policy"))
    except (TypeError, ValueError) as exc:
        raise AnalysisConfigError(
            "similar_chains.corpus_policy must be HISTORY_BEFORE_SNAPSHOT"
        ) from exc
    try:
        model_update_policy = ModelUpdatePolicy(
            raw_similar.get("model_update_policy")
        )
    except (TypeError, ValueError) as exc:
        raise AnalysisConfigError(
            "similar_chains.model_update_policy must be SNAPSHOT_VERSIONED"
        ) from exc
    if corpus_policy is not CorpusPolicy.HISTORY_BEFORE_SNAPSHOT:
        raise AnalysisConfigError(
            "production similar_chains.corpus_policy must be HISTORY_BEFORE_SNAPSHOT"
        )
    if model_update_policy is not ModelUpdatePolicy.SNAPSHOT_VERSIONED:
        raise AnalysisConfigError(
            "production similar_chains.model_update_policy must be SNAPSHOT_VERSIONED"
        )
    if raw_similar.get("temporal_cutoff") != "snapshot_time":
        raise AnalysisConfigError(
            "similar_chains.temporal_cutoff must be snapshot_time"
        )
    if raw_similar.get("exclude_same_lineage") is not True:
        raise AnalysisConfigError(
            "similar_chains.exclude_same_lineage must be true"
        )
    similar_chains = SimilarChainsPolicy(
        corpus_policy=corpus_policy,
        model_update_policy=model_update_policy,
        temporal_cutoff="snapshot_time",
        exclude_same_lineage=True,
    )
    p2_topology = _load_optional_p2_topology(document)
    historical_evidence, historical_evidence_reason = _load_optional_historical_evidence(
        document, parameters
    )
    temporal_delay, temporal_delay_reason = _load_optional_temporal_delay(document, parameters)
    (
        attribution_evaluation,
        attribution_evaluation_reason,
    ) = _load_optional_attribution_evaluation(document)
    counterfactual, counterfactual_reason = _load_optional_counterfactual(document)

    config = AnalysisConfig(
        config_version=version.strip(),
        status=status.strip(),
        parameters=parameters,
        incremental_snapshot=incremental_snapshot,
        chunk_retention=chunk_retention,
        similar_chains=similar_chains,
        historical_evidence=historical_evidence,
        historical_evidence_reason=historical_evidence_reason,
        temporal_delay=temporal_delay,
        temporal_delay_reason=temporal_delay_reason,
        p2_topology=p2_topology,
        attribution_evaluation=attribution_evaluation,
        attribution_evaluation_reason=attribution_evaluation_reason,
        counterfactual=counterfactual,
        counterfactual_reason=counterfactual_reason,
    )
    if "role.s_weak" in parameters and "role.s_min" in parameters:
        if config.value("role.s_weak") > config.value("role.s_min"):
            raise AnalysisConfigError("role.s_weak must be <= role.s_min")
    if "lineage.boundary_threshold" in parameters and "lineage.stable_threshold" in parameters:
        if config.value("lineage.boundary_threshold") > config.value("lineage.stable_threshold"):
            raise AnalysisConfigError(
                "lineage.boundary_threshold must be <= lineage.stable_threshold"
            )
    if (
        "audit.small_chain_threshold" in parameters
        and "audit.min_side_size" in parameters
        and config.value("audit.small_chain_threshold")
        < 2 * config.value("audit.min_side_size")
    ):
        raise AnalysisConfigError(
            "audit.small_chain_threshold must be at least twice "
            "audit.min_side_size"
        )
    return config
