"""Fail-closed loader for the versioned analysis parameter registry.

Low-level algorithms remain file-system independent: this module translates one
validated YAML artifact into their explicit dataclass inputs.  Every scalar
retains its source category so explanations and benchmark reports can expose
parameter provenance instead of anonymous literals (ADR-0025).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

import yaml

from descriptor import MiningConfig
from groups import RoleThresholds


class AnalysisConfigError(ValueError):
    """Raised when analysis configuration is missing or semantically invalid."""


class ParameterSource(str, Enum):
    SYSTEM_PROVIDED = "SYSTEM_PROVIDED"
    DATA_DRIVEN = "DATA_DRIVEN"
    DOCUMENTED_DEFAULT = "DOCUMENTED_DEFAULT"
    FROZEN_SPEC = "FROZEN_SPEC"


@dataclass(frozen=True)
class ConfiguredValue:
    path: str
    value: int | float
    source: ParameterSource


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
        normalized: int | float = int(value) if self.numeric_type is int else float(value)
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
_POSITIVE_FLOAT = _ParameterRule(float, 0.0, inclusive_minimum=False)
_POSITIVE_INT = _ParameterRule(int, 0, inclusive_minimum=False)
_NONNEGATIVE_INT = _ParameterRule(int, 0)


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
    "audit.rho": _PROBABILITY,
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

    config = AnalysisConfig(
        config_version=version.strip(), status=status.strip(), parameters=parameters
    )
    if "role.s_weak" in parameters and "role.s_min" in parameters:
        if config.value("role.s_weak") > config.value("role.s_min"):
            raise AnalysisConfigError("role.s_weak must be <= role.s_min")
    if "lineage.boundary_threshold" in parameters and "lineage.stable_threshold" in parameters:
        if config.value("lineage.boundary_threshold") > config.value("lineage.stable_threshold"):
            raise AnalysisConfigError(
                "lineage.boundary_threshold must be <= lineage.stable_threshold"
            )
    return config
