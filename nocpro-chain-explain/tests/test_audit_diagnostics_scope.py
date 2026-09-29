from __future__ import annotations

from pathlib import Path

import pytest

from audit_diagnostics.contracts import EvidenceState, InvocationStatus, ScopeState
from audit_diagnostics.scope import ScopePolicyError, classify_scope, load_scope_policy


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = PROJECT_ROOT / "config/audit_diagnostics/scope-v1.yaml"


def test_initial_registry_pins_full_audit_execution_profile_and_is_conservative():
    policy = load_scope_policy(DEFAULT_POLICY)

    expected = {
        "E_reference", "E_device", "E_card", "E_site", "E_remote", "S",
        "T_burst", "T_delay", "Dep_hop",
    }
    actual = {entry.channel_id for entry in policy.channels if entry.channel_id}
    assert actual == expected
    assert not any(entry.channel_id_prefix for entry in policy.channels)
    assert policy.approval_status == "UNAPPROVED_DIAGNOSTIC_POLICY"
    assert policy.capability_catalog["H"]["status"] == "EXCLUDED_BY_EXECUTION_PROFILE"
    assert policy.capability_catalog["H_domain"]["status"] == "CANDIDATE_HYPEREDGE_ONLY"


def test_missing_evidence_inputs_remain_applicable_in_initial_policy():
    policy = load_scope_policy(DEFAULT_POLICY)

    decision = classify_scope(
        ("a", "b"), "Dep_hop", policy,
        invocation=InvocationStatus.EVALUATED,
        evidence_state=EvidenceState.UNAVAILABLE,
    )

    assert decision.scope is ScopeState.APPLICABLE
    assert decision.evidence_state is EvidenceState.UNAVAILABLE


def test_unknown_channel_is_not_silently_called_not_applicable():
    policy = load_scope_policy(DEFAULT_POLICY)

    decision = classify_scope(
        ("a", "b"), "FutureChannel", policy,
        invocation=InvocationStatus.NOT_EVALUATED,
    )

    assert decision.scope is ScopeState.UNKNOWN_APPLICABILITY
    assert decision.primary_reason is not None
    assert decision.primary_reason.code == "SCOPE_RULE_UNDEFINED"


def _write_policy(path: Path, *, required_metadata: str, not_applicable_rules: str) -> None:
    path.write_text(
        f"""schema_version: audit-scope-policy-v1
policy_id: test
policy_version: '1'
approval_status: UNAPPROVED_DIAGNOSTIC_POLICY
scope_rules:
  - rule_id: all_pairs
    predicate: every_distinct_pair
  - rule_id: outside_optical
    predicate: pair_metadata_equals
    metadata_key: layer
    equals: non_optical
channels:
  - channel_id: Dep_hop
    execution_binding: test
    scope_rule_id: all_pairs
    required_scope_metadata: {required_metadata}
    not_applicable_rule_ids: {not_applicable_rules}
    missing_input_policy: applicable_unavailable
""",
        encoding="utf-8",
    )


def test_registered_not_applicable_rule_requires_scope_metadata(tmp_path):
    policy_path = tmp_path / "scope.yaml"
    _write_policy(policy_path, required_metadata="[layer]", not_applicable_rules="[outside_optical]")
    policy = load_scope_policy(policy_path)

    missing = classify_scope(
        ("a", "b"), "Dep_hop", policy,
        invocation=InvocationStatus.EVALUATED,
        evidence_state=EvidenceState.UNAVAILABLE,
    )
    not_applicable = classify_scope(
        ("a", "b"), "Dep_hop", policy,
        invocation=InvocationStatus.EVALUATED,
        evidence_state=EvidenceState.UNAVAILABLE,
        pair_scope_metadata={"layer": "non_optical"},
    )
    applicable = classify_scope(
        ("a", "b"), "Dep_hop", policy,
        invocation=InvocationStatus.EVALUATED,
        evidence_state=EvidenceState.UNAVAILABLE,
        pair_scope_metadata={"layer": "optical"},
    )

    assert missing.scope is ScopeState.UNKNOWN_APPLICABILITY
    assert missing.primary_reason.code == "SCOPE_METADATA_MISSING"
    assert not_applicable.scope is ScopeState.NOT_APPLICABLE
    assert applicable.scope is ScopeState.APPLICABLE


def test_conflicting_scope_metadata_is_unknown(tmp_path):
    policy_path = tmp_path / "scope.yaml"
    _write_policy(policy_path, required_metadata="[layer]", not_applicable_rules="[]")
    policy = load_scope_policy(policy_path)

    decision = classify_scope(
        ("a", "b"), "Dep_hop", policy,
        invocation=InvocationStatus.NOT_EVALUATED,
        pair_scope_metadata={"layer": ["optical", "non_optical"]},
    )

    assert decision.scope is ScopeState.UNKNOWN_APPLICABILITY
    assert decision.primary_reason.code == "SCOPE_METADATA_CONFLICT"


def test_policy_rejects_unknown_rule_reference(tmp_path):
    policy_path = tmp_path / "scope.yaml"
    policy_path.write_text(
        """schema_version: audit-scope-policy-v1
policy_id: test
policy_version: '1'
approval_status: UNAPPROVED_DIAGNOSTIC_POLICY
scope_rules:
  - rule_id: all_pairs
    predicate: every_distinct_pair
channels:
  - channel_id: Dep_hop
    execution_binding: test
    scope_rule_id: missing
    required_scope_metadata: []
    not_applicable_rule_ids: []
    missing_input_policy: applicable_unavailable
""",
        encoding="utf-8",
    )

    with pytest.raises(ScopePolicyError, match="unknown scope rule"):
        load_scope_policy(policy_path)
