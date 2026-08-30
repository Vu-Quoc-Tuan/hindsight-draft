"""Versioned analysis configuration invariants (ADR-0025)."""

from __future__ import annotations

from pathlib import Path

import pytest

from configuration import (
    AnalysisConfigError,
    ParameterSource,
    load_analysis_config,
)
from similar_chains import CorpusPolicy, ModelUpdatePolicy
from tier1b import analyze_chain_configured
from tests.test_tier1b_analysis import _alarm, _snapshot


ROOT = Path(__file__).resolve().parents[1]
SHIPPED_CONFIG = ROOT / "config/thresholds/v1.yaml"

COMPLETE_P2_YAML = (
    SHIPPED_CONFIG.read_text(encoding="utf-8")
    + """

propagation:
  config_version: propagation-test-v1
  rwr:
    restart_probability: {value: 0.2, source: DATA_DRIVEN}
    convergence_tolerance: {value: 0.001, source: FROZEN_SPEC}
    max_iterations: {value: 100, source: DOCUMENTED_DEFAULT}
  temporal:
    decay_type: exponential
    decay_parameter: {value: 30.0, source: DATA_DRIVEN}
  acceptance:
    score_threshold: {value: 0.5, source: FROZEN_SPEC}
  limits:
    max_candidate_edges: {value: 500, source: DOCUMENTED_DEFAULT}

dependency_scope:
  limits:
    max_scope_resources: {value: 1000, source: FROZEN_SPEC}
    max_materialized_resources: {value: 100, source: DOCUMENTED_DEFAULT}
"""
)


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "analysis.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_shipped_config_keeps_p2_fail_closed():
    config = load_analysis_config(SHIPPED_CONFIG)

    assert config.p2_topology.propagation is None
    assert config.p2_topology.propagation_reason == "PROPAGATION_CONFIG_INCOMPLETE"
    assert config.p2_topology.dependency_scope is None
    assert (
        config.p2_topology.dependency_scope_reason
        == "DEPENDENCY_SCOPE_CONFIG_INCOMPLETE"
    )


def test_complete_p2_config_preserves_parameter_provenance(tmp_path: Path):
    config = load_analysis_config(_write(tmp_path, COMPLETE_P2_YAML))

    propagation = config.p2_topology.propagation
    dependency_scope = config.p2_topology.dependency_scope

    assert propagation is not None
    assert propagation.config_version == "propagation-test-v1"
    assert propagation.restart_probability.value == 0.2
    assert propagation.restart_probability.source is ParameterSource.DATA_DRIVEN
    assert propagation.convergence_tolerance.value == 0.001
    assert propagation.convergence_tolerance.source is ParameterSource.FROZEN_SPEC
    assert propagation.max_iterations.value == 100
    assert propagation.max_iterations.source is ParameterSource.DOCUMENTED_DEFAULT
    assert propagation.decay_type == "exponential"
    assert propagation.decay_parameter.value == 30.0
    assert propagation.decay_parameter.source is ParameterSource.DATA_DRIVEN
    assert propagation.score_threshold.value == 0.5
    assert propagation.score_threshold.source is ParameterSource.FROZEN_SPEC
    assert propagation.max_candidate_edges.value == 500
    assert propagation.max_candidate_edges.source is ParameterSource.DOCUMENTED_DEFAULT
    assert dependency_scope is not None
    assert dependency_scope.max_scope_resources.value == 1000
    assert dependency_scope.max_scope_resources.source is ParameterSource.FROZEN_SPEC
    assert dependency_scope.max_materialized_resources.value == 100
    assert (
        dependency_scope.max_materialized_resources.source
        is ParameterSource.DOCUMENTED_DEFAULT
    )
    assert config.p2_topology.propagation_reason is None
    assert config.p2_topology.dependency_scope_reason is None


@pytest.mark.parametrize(
    "line",
    [
        "  config_version: propagation-test-v1\n",
        "    restart_probability: {value: 0.2, source: DATA_DRIVEN}\n",
        "    convergence_tolerance: {value: 0.001, source: FROZEN_SPEC}\n",
        "    max_iterations: {value: 100, source: DOCUMENTED_DEFAULT}\n",
        "    decay_type: exponential\n",
        "    decay_parameter: {value: 30.0, source: DATA_DRIVEN}\n",
        "    score_threshold: {value: 0.5, source: FROZEN_SPEC}\n",
        "    max_candidate_edges: {value: 500, source: DOCUMENTED_DEFAULT}\n",
    ],
)
def test_incomplete_propagation_config_fails_closed_without_blocking_p0_p1(
    tmp_path: Path, line: str
):
    config = load_analysis_config(_write(tmp_path, COMPLETE_P2_YAML.replace(line, "")))

    assert config.p2_topology.propagation is None
    assert config.p2_topology.propagation_reason == "PROPAGATION_CONFIG_INCOMPLETE"
    assert config.value("role.c_min") == 0.5


@pytest.mark.parametrize(
    "line",
    [
        "    max_scope_resources: {value: 1000, source: FROZEN_SPEC}\n",
        "    max_materialized_resources: {value: 100, source: DOCUMENTED_DEFAULT}\n",
    ],
)
def test_incomplete_dependency_scope_config_fails_closed_without_blocking_p0_p1(
    tmp_path: Path, line: str
):
    config = load_analysis_config(_write(tmp_path, COMPLETE_P2_YAML.replace(line, "")))

    assert config.p2_topology.dependency_scope is None
    assert (
        config.p2_topology.dependency_scope_reason
        == "DEPENDENCY_SCOPE_CONFIG_INCOMPLETE"
    )
    assert config.value("role.c_min") == 0.5


@pytest.mark.parametrize(
    ("old", "new", "reason"),
    [
        (
            "  config_version: propagation-test-v1",
            "  config_version: ''",
            "PROPAGATION_CONFIG_INCOMPLETE",
        ),
        (
            "    restart_probability: {value: 0.2, source: DATA_DRIVEN}",
            "    restart_probability: {value: 0, source: DATA_DRIVEN}",
            "PROPAGATION_CONFIG_INCOMPLETE",
        ),
        (
            "    restart_probability: {value: 0.2, source: DATA_DRIVEN}",
            "    restart_probability: {value: 1, source: DATA_DRIVEN}",
            "PROPAGATION_CONFIG_INCOMPLETE",
        ),
        (
            "    restart_probability: {value: 0.2, source: DATA_DRIVEN}",
            "    restart_probability: {value: .nan, source: DATA_DRIVEN}",
            "PROPAGATION_CONFIG_INCOMPLETE",
        ),
        (
            "    convergence_tolerance: {value: 0.001, source: FROZEN_SPEC}",
            "    convergence_tolerance: {value: 0, source: FROZEN_SPEC}",
            "PROPAGATION_CONFIG_INCOMPLETE",
        ),
        (
            "    max_iterations: {value: 100, source: DOCUMENTED_DEFAULT}",
            "    max_iterations: {value: 0, source: DOCUMENTED_DEFAULT}",
            "PROPAGATION_CONFIG_INCOMPLETE",
        ),
        (
            "    decay_type: exponential",
            "    decay_type: linear",
            "PROPAGATION_CONFIG_INCOMPLETE",
        ),
        (
            "    decay_parameter: {value: 30.0, source: DATA_DRIVEN}",
            "    decay_parameter: {value: 0, source: DATA_DRIVEN}",
            "PROPAGATION_CONFIG_INCOMPLETE",
        ),
        (
            "    score_threshold: {value: 0.5, source: FROZEN_SPEC}",
            "    score_threshold: {value: -0.1, source: FROZEN_SPEC}",
            "PROPAGATION_CONFIG_INCOMPLETE",
        ),
        (
            "    score_threshold: {value: 0.5, source: FROZEN_SPEC}",
            "    score_threshold: {value: 1.1, source: FROZEN_SPEC}",
            "PROPAGATION_CONFIG_INCOMPLETE",
        ),
        (
            "    max_candidate_edges: {value: 500, source: DOCUMENTED_DEFAULT}",
            "    max_candidate_edges: {value: 0, source: DOCUMENTED_DEFAULT}",
            "PROPAGATION_CONFIG_INCOMPLETE",
        ),
        (
            "    max_scope_resources: {value: 1000, source: FROZEN_SPEC}",
            "    max_scope_resources: {value: 0, source: FROZEN_SPEC}",
            "DEPENDENCY_SCOPE_CONFIG_INCOMPLETE",
        ),
        (
            "    max_materialized_resources: {value: 100, source: DOCUMENTED_DEFAULT}",
            "    max_materialized_resources: {value: 0, source: DOCUMENTED_DEFAULT}",
            "DEPENDENCY_SCOPE_CONFIG_INCOMPLETE",
        ),
        (
            "    max_materialized_resources: {value: 100, source: DOCUMENTED_DEFAULT}",
            "    max_materialized_resources: {value: 1001, source: DOCUMENTED_DEFAULT}",
            "DEPENDENCY_SCOPE_CONFIG_INCOMPLETE",
        ),
    ],
)
def test_invalid_complete_p2_config_fails_closed_without_blocking_p0_p1(
    tmp_path: Path, old: str, new: str, reason: str
):
    config = load_analysis_config(_write(tmp_path, COMPLETE_P2_YAML.replace(old, new, 1)))

    if reason == "PROPAGATION_CONFIG_INCOMPLETE":
        assert config.p2_topology.propagation is None
        assert config.p2_topology.propagation_reason == reason
    else:
        assert config.p2_topology.dependency_scope is None
        assert config.p2_topology.dependency_scope_reason == reason
    assert config.value("role.c_min") == 0.5


def test_shipped_v1_config_constructs_engine_configs_with_one_version():
    config = load_analysis_config(SHIPPED_CONFIG)

    role = config.role_thresholds()
    mining = config.mining_config()

    assert config.config_version == "v1"
    assert role.config_version == "v1"
    assert mining.config_version == "v1"
    assert role.c_min == config.parameter("role.c_min").value
    assert mining.max_depth == config.parameter("descriptor.max_depth").value
    assert config.incremental_snapshot.mode.value == "disabled"
    assert config.incremental_snapshot.reason == (
        "sequential_production_snapshots_not_available"
    )
    assert config.similar_chains.corpus_policy is CorpusPolicy.HISTORY_BEFORE_SNAPSHOT
    assert (
        config.similar_chains.model_update_policy
        is ModelUpdatePolicy.SNAPSHOT_VERSIONED
    )
    assert config.similar_chains.temporal_cutoff == "snapshot_time"
    assert config.similar_chains.exclude_same_lineage is True


@pytest.mark.parametrize(
    ("field", "old", "new", "message"),
    [
        (
            "corpus_policy",
            "HISTORY_BEFORE_SNAPSHOT",
            "FROZEN_TRAINING",
            "production similar_chains.corpus_policy",
        ),
        (
            "model_update_policy",
            "SNAPSHOT_VERSIONED",
            "FROZEN",
            "production similar_chains.model_update_policy",
        ),
        ("temporal_cutoff", "snapshot_time", "produced_at", "temporal_cutoff"),
        ("exclude_same_lineage", "true", "false", "exclude_same_lineage"),
    ],
)
def test_production_similarity_policy_fails_closed(
    tmp_path: Path, field: str, old: str, new: str, message: str
):
    text = SHIPPED_CONFIG.read_text(encoding="utf-8").replace(
        f"  {field}: {old}\n", f"  {field}: {new}\n"
    )
    with pytest.raises(AnalysisConfigError, match=message):
        load_analysis_config(_write(tmp_path, text))


def test_incremental_policy_requires_reason_when_explicitly_disabled(tmp_path: Path):
    text = SHIPPED_CONFIG.read_text(encoding="utf-8").replace(
        "  reason: sequential_production_snapshots_not_available\n", ""
    )
    with pytest.raises(AnalysisConfigError, match="incremental_snapshot.reason"):
        load_analysis_config(_write(tmp_path, text))


def test_incremental_policy_rejects_unbenchmarked_enablement(tmp_path: Path):
    text = SHIPPED_CONFIG.read_text(encoding="utf-8").replace(
        "mode: disabled", "mode: enabled"
    )
    with pytest.raises(AnalysisConfigError, match="only supports disabled"):
        load_analysis_config(_write(tmp_path, text))


def test_every_required_parameter_carries_an_allowed_source():
    config = load_analysis_config(SHIPPED_CONFIG)

    assert set(config.parameters) == set(config.REQUIRED_PARAMETERS)
    assert all(isinstance(item.source, ParameterSource) for item in config.parameters.values())
    assert config.parameter("role.min_computable_groups").source is ParameterSource.FROZEN_SPEC


def test_missing_config_version_fails_closed(tmp_path: Path):
    path = _write(tmp_path, "role: {}\n")
    with pytest.raises(AnalysisConfigError, match="config_version"):
        load_analysis_config(path)


def test_missing_required_parameter_fails_closed(tmp_path: Path):
    path = _write(tmp_path, "config_version: v1\nstatus: baseline\n")
    with pytest.raises(AnalysisConfigError, match="temporal.burst.gap_seconds"):
        load_analysis_config(path)


def test_missing_parameter_source_fails_closed(tmp_path: Path):
    path = _write(
        tmp_path,
        """
config_version: v1
temporal:
  burst:
    gap_seconds:
      value: 30
""",
    )
    with pytest.raises(AnalysisConfigError, match="source"):
        load_analysis_config(path, required_parameters=("temporal.burst.gap_seconds",))


def test_unknown_parameter_source_fails_closed(tmp_path: Path):
    path = _write(
        tmp_path,
        """
config_version: v1
temporal:
  burst:
    gap_seconds:
      value: 30
      source: GUESSED
""",
    )
    with pytest.raises(AnalysisConfigError, match="GUESSED"):
        load_analysis_config(path, required_parameters=("temporal.burst.gap_seconds",))


@pytest.mark.parametrize(
    ("path_name", "value"),
    [
        ("role.c_min", -0.1),
        ("role.c_min", 1.1),
        ("descriptor.max_depth", 0),
        ("dependency.lambda_dep", 0),
        ("audit.rho", 0.6),
    ],
)
def test_invalid_parameter_ranges_fail_closed(
    tmp_path: Path, path_name: str, value: float
):
    segments = path_name.split(".")
    text = "config_version: v1\n"
    indent = ""
    for segment in segments:
        text += f"{indent}{segment}:\n"
        indent += "  "
    text += f"{indent}value: {value}\n{indent}source: DOCUMENTED_DEFAULT\n"

    path = _write(tmp_path, text)
    with pytest.raises(AnalysisConfigError, match=path_name):
        load_analysis_config(path, required_parameters=(path_name,))


def test_parameter_lookup_is_fail_closed_for_unknown_path():
    config = load_analysis_config(SHIPPED_CONFIG)
    with pytest.raises(AnalysisConfigError, match="unknown parameter"):
        config.parameter("role.not_a_real_threshold")


def test_audit_small_chain_threshold_must_make_both_sides_feasible(tmp_path: Path):
    text = SHIPPED_CONFIG.read_text(encoding="utf-8").replace(
        "small_chain_threshold: {value: 10, source: FROZEN_SPEC}",
        "small_chain_threshold: {value: 8, source: FROZEN_SPEC}",
        1,
    )

    with pytest.raises(AnalysisConfigError, match="twice audit.min_side_size"):
        load_analysis_config(_write(tmp_path, text))


def test_configured_tier1b_stamps_one_version_through_all_outputs():
    alarms = [
        _alarm(
            f"a{i}",
            "C1",
            device_code="D1",
            node_reference="R1",
            alarm_name="LINK DOWN",
            location_code="SITE_A",
            canonical_start_time=f"2026-01-01T00:00:{i:02d}",
        )
        for i in range(3)
    ]
    package = _snapshot(
        alarms,
        [{"chain_id": "C1", "snapshot_id": "s1", "member_count": 3}],
        [
            {"chain_id": "C1", "alarm_id": alarm["alarm_id"], "snapshot_id": "s1"}
            for alarm in alarms
        ],
    )
    config = load_analysis_config(SHIPPED_CONFIG)

    analysis = analyze_chain_configured(
        package, "C1", analysis_config=config, enable_contrastive=False
    )

    assert analysis.config_version == "v1"
    assert analysis.descriptors.config_version == "v1"
    assert {member.role.config_version for member in analysis.members.values()} == {"v1"}
    assert analysis.parameter_provenance["role.min_computable_groups"] == "FROZEN_SPEC"
    assert analysis.parameter_provenance["role.c_min"] == "DOCUMENTED_DEFAULT"
