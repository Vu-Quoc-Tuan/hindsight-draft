"""Layer 4 — system pair metadata typing (docs 07 §7, Decision 3).

Frozen rules:
  - explicit pairs for correctness fixtures
  - veto keeps raw_score=-999999999 plus system_semantic=VETO
  - NOT_EVALUATED / UNKNOWN carry raw_score=null
  - coverage_scope at batch level, never per pair
  - every pair result carries attribute_ref
"""

from __future__ import annotations

import dataclasses

import pytest
import yaml

from nocpro_mock.contract import (
    TIMEWINDOW_VETO_SENTINEL,
    CoverageScope,
    PairMetadata,
    ProvenanceClass,
    SourceKind,
    SystemPairStatus,
    SystemSemantic,
)
from nocpro_mock.scenarios import (
    GENERATOR_TYPE_DETERMINISTIC,
    ScenarioError,
    generate_system_pair_metadata,
    load_scenario,
)
from tests.conftest import REPO_ROOT

FIXTURE = REPO_ROOT / "docs/examples/synthetic/scenario_system_pair_metadata.yaml"
VERSION = "nocpro-mock-0.1.0"
CHAIN = "SYN-CHAIN-1"


@pytest.fixture()
def generated():
    scenario = load_scenario(FIXTURE)
    return generate_system_pair_metadata(
        scenario, generator_version=VERSION, chain_id=CHAIN
    )


def _write(tmp_path, block):
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "s.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "scenario_id": "s_v1",
                "source_kind": "SYNTHETIC_TEST",
                "seed": 42,
                "system_pair_metadata": block,
            }
        ),
        encoding="utf-8",
    )
    return load_scenario(path)


def test_all_typing_cases_are_materialized(generated):
    pairs, batches, configs = generated
    assert len(pairs) == 5
    assert len(batches) == 1
    assert len(configs) == 1
    statuses = [p.system_pair_status for p in pairs]
    assert statuses.count(SystemPairStatus.EVALUATED) == 3
    assert SystemPairStatus.NOT_EVALUATED in statuses
    assert SystemPairStatus.UNKNOWN in statuses


def test_veto_preserves_the_raw_sentinel(generated):
    """A null score would discard the raw SYSTEM_FACT value."""
    pairs, _, _ = generated
    veto = next(p for p in pairs if p.system_semantic is SystemSemantic.VETO)
    assert veto.raw_score == TIMEWINDOW_VETO_SENTINEL
    assert veto.veto is True


def test_out_of_range_score_is_kept_raw(generated):
    """Raw score 2.0 is preserved, never clamped into [0,1]."""
    pairs, _, _ = generated
    scores = {p.raw_score for p in pairs if p.raw_score is not None}
    assert 2.0 in scores


def test_unevaluated_pairs_have_no_score_or_semantic(generated):
    pairs, _, _ = generated
    for pair in pairs:
        if pair.system_pair_status is not SystemPairStatus.EVALUATED:
            assert pair.raw_score is None
            assert pair.system_semantic is None


def test_coverage_scope_is_batch_level_only(generated):
    """coverage_scope describes the export, so it must not exist on a pair."""
    pairs, batches, _ = generated
    assert batches[0].coverage_scope is CoverageScope.BOUNDED_COMPARISON
    pair_fields = {f.name for f in dataclasses.fields(PairMetadata)}
    assert "coverage_scope" not in pair_fields
    assert batches[0].pair_count == len(pairs)


def test_every_pair_carries_an_attribute_ref(generated):
    """A raw score is uninterpretable without knowing which Attribute made it."""
    pairs, batches, configs = generated
    assert all(p.attribute_ref == "SYN-ATTR-TIMEWINDOW-01" for p in pairs)
    assert batches[0].attribute_ref == "SYN-ATTR-TIMEWINDOW-01"
    assert configs[0].attribute_ref == "SYN-ATTR-TIMEWINDOW-01"


def test_attribute_ref_resolves_to_an_emitted_config(generated):
    pairs, _, configs = generated
    known = {c.attribute_ref for c in configs}
    assert all(p.attribute_ref in known for p in pairs)


def test_pair_metadata_is_system_fact(generated):
    pairs, batches, configs = generated
    assert all(p.provenance_class is ProvenanceClass.SYSTEM_FACT for p in pairs)
    assert batches[0].provenance_class is ProvenanceClass.SYSTEM_FACT
    assert configs[0].provenance_class is ProvenanceClass.SYSTEM_FACT


def test_attribute_config_holds_no_raw_score(generated):
    """docs 03: never put a raw pair score in M_attribute_config."""
    _, _, configs = generated
    config_fields = {f.name for f in dataclasses.fields(type(configs[0]))}
    assert "raw_score" not in config_fields
    assert configs[0].attribute_type == 3


def test_missing_attribute_ref_is_refused(tmp_path):
    scenario = _write(
        tmp_path,
        {
            "coverage_scope": "UNKNOWN",
            "pairs": [
                {
                    "alarm_id_a": "SYN-A-1",
                    "alarm_id_b": "SYN-A-2",
                    "system_pair_status": "EVALUATED",
                    "raw_score": 1.0,
                    "system_semantic": "SUPPORT",
                }
            ],
        },
    )
    with pytest.raises(ScenarioError, match="requires attribute_ref"):
        generate_system_pair_metadata(
            scenario, generator_version=VERSION, chain_id=CHAIN
        )


def test_veto_semantic_without_the_sentinel_is_refused(tmp_path):
    scenario = _write(
        tmp_path,
        {
            "attribute_ref": "SYN-ATTR-1",
            "pairs": [
                {
                    "alarm_id_a": "SYN-A-1",
                    "alarm_id_b": "SYN-A-2",
                    "system_pair_status": "EVALUATED",
                    "raw_score": None,
                    "system_semantic": "VETO",
                }
            ],
        },
    )
    with pytest.raises(ScenarioError, match="must preserve"):
        generate_system_pair_metadata(
            scenario, generator_version=VERSION, chain_id=CHAIN
        )


def test_sentinel_without_veto_semantic_is_refused(tmp_path):
    scenario = _write(
        tmp_path,
        {
            "attribute_ref": "SYN-ATTR-1",
            "pairs": [
                {
                    "alarm_id_a": "SYN-A-1",
                    "alarm_id_b": "SYN-A-2",
                    "system_pair_status": "EVALUATED",
                    "raw_score": TIMEWINDOW_VETO_SENTINEL,
                    "system_semantic": "SUPPORT",
                }
            ],
        },
    )
    with pytest.raises(ScenarioError, match="must declare system_semantic=VETO"):
        generate_system_pair_metadata(
            scenario, generator_version=VERSION, chain_id=CHAIN
        )


@pytest.mark.parametrize("status", ["NOT_EVALUATED", "UNKNOWN"])
def test_unevaluated_pair_with_a_score_is_refused(tmp_path, status):
    scenario = _write(
        tmp_path,
        {
            "attribute_ref": "SYN-ATTR-1",
            "pairs": [
                {
                    "alarm_id_a": "SYN-A-1",
                    "alarm_id_b": "SYN-A-2",
                    "system_pair_status": status,
                    "raw_score": 1.0,
                }
            ],
        },
    )
    with pytest.raises(ScenarioError, match="must have raw_score=null"):
        generate_system_pair_metadata(
            scenario, generator_version=VERSION, chain_id=CHAIN
        )


def test_duplicate_pair_is_refused(tmp_path):
    """(A,B) and (B,A) are the same undirected pair."""
    scenario = _write(
        tmp_path,
        {
            "attribute_ref": "SYN-ATTR-1",
            "pairs": [
                {
                    "alarm_id_a": "SYN-A-1",
                    "alarm_id_b": "SYN-A-2",
                    "system_pair_status": "UNKNOWN",
                },
                {
                    "alarm_id_a": "SYN-A-2",
                    "alarm_id_b": "SYN-A-1",
                    "system_pair_status": "UNKNOWN",
                },
            ],
        },
    )
    with pytest.raises(ScenarioError, match="duplicate pair"):
        generate_system_pair_metadata(
            scenario, generator_version=VERSION, chain_id=CHAIN
        )


def test_declaring_both_pairs_and_generator_is_refused(tmp_path):
    scenario = _write(
        tmp_path,
        {
            "attribute_ref": "SYN-ATTR-1",
            "pairs": [
                {
                    "alarm_id_a": "SYN-A-1",
                    "alarm_id_b": "SYN-A-2",
                    "system_pair_status": "UNKNOWN",
                }
            ],
            "generator": {
                "type": GENERATOR_TYPE_DETERMINISTIC,
                "alarm_count": 10,
                "max_compare_per_alarm": 2,
            },
        },
    )
    with pytest.raises(ScenarioError, match="not both"):
        generate_system_pair_metadata(
            scenario, generator_version=VERSION, chain_id=CHAIN
        )


# --------------------------------------------------------------------------
# Deterministic generator mode (scale tests)
# --------------------------------------------------------------------------


def _generator_scenario(tmp_path, **overrides):
    spec = {
        "type": GENERATOR_TYPE_DETERMINISTIC,
        "seed": 42,
        "alarm_count": 50,
        "max_compare_per_alarm": 3,
        "scoring_rule": "SAME_SYNTHETIC_REFERENCE",
    }
    spec.update(overrides)
    return _write(
        tmp_path,
        {
            "attribute_ref": "SYN-ATTR-REF-01",
            "coverage_scope": "BOUNDED_COMPARISON",
            "generator": spec,
        },
    )


def test_generator_mode_materializes_canonical_records(tmp_path):
    """Downstream must not be able to tell a generated pair from an explicit one."""
    scenario = _generator_scenario(tmp_path)
    pairs, batches, configs = generate_system_pair_metadata(
        scenario, generator_version=VERSION, chain_id=CHAIN
    )
    assert pairs
    assert all(isinstance(p, PairMetadata) for p in pairs)
    assert all(p.attribute_ref == "SYN-ATTR-REF-01" for p in pairs)
    assert all(p.chain_id == CHAIN for p in pairs)
    assert batches[0].max_compare_per_alarm == 3
    assert configs[0].attribute_ref == "SYN-ATTR-REF-01"


def test_generator_mode_is_bounded(tmp_path):
    """Must not materialize C(N,2); ADR-0015 forbids unguarded pair explosion."""
    scenario = _generator_scenario(tmp_path, alarm_count=200, max_compare_per_alarm=2)
    pairs, _, _ = generate_system_pair_metadata(
        scenario, generator_version=VERSION, chain_id=CHAIN
    )
    full_pair_space = 200 * 199 // 2
    assert len(pairs) <= 200 * 2
    assert len(pairs) < full_pair_space


def test_generator_mode_is_deterministic(tmp_path):
    scenario = _generator_scenario(tmp_path)
    first, _, _ = generate_system_pair_metadata(
        scenario, generator_version=VERSION, chain_id=CHAIN
    )
    second, _, _ = generate_system_pair_metadata(
        scenario, generator_version=VERSION, chain_id=CHAIN
    )
    assert first == second


def test_generator_seed_changes_output(tmp_path):
    a, _, _ = generate_system_pair_metadata(
        _generator_scenario(tmp_path / "a", seed=42),
        generator_version=VERSION,
        chain_id=CHAIN,
    )
    b, _, _ = generate_system_pair_metadata(
        _generator_scenario(tmp_path / "b", seed=7),
        generator_version=VERSION,
        chain_id=CHAIN,
    )
    assert a != b


def test_generator_records_its_rule(tmp_path):
    scenario = _generator_scenario(tmp_path)
    _, batches, _ = generate_system_pair_metadata(
        scenario, generator_version=VERSION, chain_id=CHAIN
    )
    rule = batches[0].generation.generation_rule
    assert GENERATOR_TYPE_DETERMINISTIC in rule
    assert "max_compare_per_alarm=3" in rule


def test_unknown_generator_type_is_refused(tmp_path):
    scenario = _generator_scenario(tmp_path, type="MAGIC")
    with pytest.raises(ScenarioError, match="unknown pair generator type"):
        generate_system_pair_metadata(
            scenario, generator_version=VERSION, chain_id=CHAIN
        )


def test_generator_requires_a_compare_bound(tmp_path):
    scenario = _generator_scenario(tmp_path, max_compare_per_alarm=0)
    with pytest.raises(ScenarioError, match="max_compare_per_alarm"):
        generate_system_pair_metadata(
            scenario, generator_version=VERSION, chain_id=CHAIN
        )


def test_generated_pairs_are_synthetic_named(tmp_path):
    scenario = _generator_scenario(tmp_path, alarm_count=10)
    pairs, _, _ = generate_system_pair_metadata(
        scenario, generator_version=VERSION, chain_id=CHAIN
    )
    for pair in pairs:
        assert pair.alarm_id_a.startswith("SYN-A-")
        assert pair.alarm_id_b.startswith("SYN-A-")
