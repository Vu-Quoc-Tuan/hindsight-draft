"""Similar Chains tests (§8.3, ADR-0022).

Pinned invariants:
  - fingerprint is deterministic for fixed input
  - alarm-taxonomy resolution is FAMILY, then TYPE_FALLBACK, then no term
  - FAMILY and TYPE_FALLBACK terms are namespaced and cannot collide
  - device_type_name is used verbatim, never guessed from a device-code prefix
  - missing duration gets its own bin, not bin 0
  - cosine similarity is deterministic and in [0,1]
  - all fingerprints scored in one request must share one FingerprintModel
  - the nearest "different incident" result excludes the same lineage component
  - "previous states of this chain" mode returns exactly the same-lineage chains
  - equal-similarity results break ties deterministically by chain_id
"""

from __future__ import annotations

import pytest

from channels.semantic import AlarmTaxonomy
from descriptor.metrics import DescriptorMetrics
from descriptor.mining import Descriptor, DescriptorKind
from descriptor.predicates import Predicate
from libs.contracts import IngestedAlarm
from similar_chains import (
    ChainFingerprint,
    CorpusPolicy,
    ModelVersionMismatch,
    ModelUpdatePolicy,
    TaxonomyLevel,
    TermVector,
    TimedChainFingerprint,
    build_fingerprint,
    cosine_similarity,
    duration_bin,
    find_similar_chains,
    fit_fingerprint_model,
    materialize_similarity_index,
    previous_states_of_chain,
    size_bin,
)
from similar_chains.fingerprint import _family_term


def alarm(alarm_id: str, **fields) -> IngestedAlarm:
    raw = {k: str(v) for k, v in fields.items() if v is not None}
    return IngestedAlarm(
        alarm_id=alarm_id,
        snapshot_id="s1",
        raw=raw,
        alarm_name=fields.get("alarm_name"),
        device_code=fields.get("device_code"),
    )


def descriptor(label_value: str) -> Descriptor:
    return Descriptor(
        kind=DescriptorKind.IDENTITY,
        predicates=(Predicate(field="device_code", value=label_value, derivation_tag="device"),),
        extent=0,
        metrics=DescriptorMetrics(true_positives=1, false_positives=0, target_size=1, universe_size=10),
    )


MODEL_V1 = "sim-v1"


def _model(fingerprints, version=MODEL_V1):
    return fit_fingerprint_model(fingerprints, model_version=version)


# --------------------------------------------------------------------------
# Bins
# --------------------------------------------------------------------------


def test_size_bin_is_monotonic():
    assert size_bin(1) != size_bin(1000)


def test_duration_bin_none_gets_its_own_bin():
    """A missing duration must not collapse into bin 0."""
    unknown = duration_bin(None)
    zero_duration = duration_bin(0)
    assert unknown != zero_duration
    assert unknown == "duration_bin_unknown"


def test_duration_bin_is_deterministic():
    assert duration_bin(45) == duration_bin(45)
    assert duration_bin(45) != duration_bin(4500)


# --------------------------------------------------------------------------
# Alarm taxonomy resolution: FAMILY -> TYPE_FALLBACK -> none
# --------------------------------------------------------------------------


def test_family_resolves_from_taxonomy_when_available():
    taxonomy = AlarmTaxonomy(families={"LINK DOWN": "LINK"}, categories={})
    term = _family_term(alarm("a1", alarm_name="LINK DOWN", alarm_type_name="CONNECTIVITY"), taxonomy)
    assert term.level is TaxonomyLevel.FAMILY
    assert term.value == "LINK"


def test_type_fallback_used_when_no_taxonomy_matches():
    """This is a data-adapter fallback (TYPE_FALLBACK), not the T_delay/H backoff rule."""
    from channels.semantic import EMPTY_TAXONOMY

    term = _family_term(
        alarm("a1", alarm_name="LINK DOWN", alarm_type_name="CONNECTIVITY"), EMPTY_TAXONOMY
    )
    assert term.level is TaxonomyLevel.TYPE_FALLBACK
    assert term.value == "CONNECTIVITY"


def test_no_term_when_neither_family_nor_type_available():
    """Real export case: alarm_type_name empty and no taxonomy given. Never guessed."""
    from channels.semantic import EMPTY_TAXONOMY

    term = _family_term(alarm("a1", alarm_name="LINK DOWN", alarm_type_name=""), EMPTY_TAXONOMY)
    assert term is None


def test_family_and_type_fallback_terms_are_namespaced_and_cannot_collide():
    """A FAMILY value and a differently-sourced TYPE_FALLBACK value must not
    collide in the vocabulary even if they happen to share spelling."""
    taxonomy = AlarmTaxonomy(families={"X": "DIAMETER"}, categories={})
    with_family = build_fingerprint("A", [alarm("a1", alarm_name="X")], taxonomy=taxonomy)
    with_type_fallback = build_fingerprint(
        "B", [alarm("a1", alarm_name="Y", alarm_type_name="DIAMETER")]
    )
    family_key = next(iter(with_family.family_terms.counts))
    fallback_key = next(iter(with_type_fallback.family_terms.counts))
    assert family_key != fallback_key
    assert family_key.startswith("FAMILY:")
    assert fallback_key.startswith("TYPE_FALLBACK:")


def test_device_type_is_used_verbatim_not_guessed_from_prefix():
    """device_type_name is a real column; it must not be derived from device_code."""
    fp = build_fingerprint("C1", [alarm("a1", device_code="HLC9102DEA01", device_type_name="ROUTER")])
    assert fp.device_type_terms.counts == {"ROUTER": 1}


# --------------------------------------------------------------------------
# Fingerprint determinism and diagnostics
# --------------------------------------------------------------------------


def test_fingerprint_is_deterministic():
    alarms = [
        alarm("a1", alarm_name="X", alarm_type_name="T1", device_type_name="D1"),
        alarm("a2", alarm_name="Y", alarm_type_name="T2", device_type_name="D2"),
    ]
    fp1 = build_fingerprint("C1", alarms, identity_descriptors=(descriptor("V1"),))
    fp2 = build_fingerprint("C1", alarms, identity_descriptors=(descriptor("V1"),))
    assert fp1 == fp2


def test_descriptor_terms_are_capped_at_top_k():
    descriptors = tuple(descriptor(f"V{i}") for i in range(10))
    fp = build_fingerprint(
        "C1", [alarm("a1")], identity_descriptors=descriptors, top_descriptor_predicates=3
    )
    assert len(fp.descriptor_terms) == 3


def test_active_and_missing_blocks_are_complementary():
    fp = build_fingerprint("C1", [alarm("a1", device_type_name="STP")])
    active = set(fp.active_blocks())
    missing = set(fp.missing_blocks())
    assert active.isdisjoint(missing)
    assert active | missing == {
        "alarm_taxonomy", "device_type", "identity_descriptors", "size_bin", "duration_bin"
    }
    assert "device_type" in active
    assert "alarm_taxonomy" in missing


def test_size_and_duration_blocks_are_always_active():
    """build_fingerprint never produces a fingerprint missing these two."""
    fp = build_fingerprint("C1", [alarm("a1")])
    assert "size_bin" in fp.active_blocks()
    assert "duration_bin" in fp.active_blocks()


# --------------------------------------------------------------------------
# Cosine similarity
# --------------------------------------------------------------------------


def _fp(chain_id: str, family: list[str], device: list[str], lineage: str | None = None) -> ChainFingerprint:
    return ChainFingerprint(
        chain_id=chain_id,
        lineage_component_id=lineage,
        family_terms=TermVector.from_terms(family),
        device_type_terms=TermVector.from_terms(device),
        descriptor_terms=(),
        size_bin=size_bin(1),
        duration_bin=duration_bin(10),
        member_count=1,
    )


def test_identical_fingerprints_have_similarity_one():
    fps = [_fp("A", ["F1"], ["D1"]), _fp("B", ["F1"], ["D1"])]
    model = _model(fps)
    score = cosine_similarity(fps[0], fps[1], model=model)
    assert score == pytest.approx(1.0)


def test_disjoint_fingerprints_have_low_similarity():
    fps = [_fp("A", ["F1"], ["D1"]), _fp("B", ["F2"], ["D2"])]
    model = _model(fps)
    score = cosine_similarity(fps[0], fps[1], model=model)
    assert 0.0 <= score < 1.0


def test_similarity_is_within_unit_interval():
    fps = [_fp(f"C{i}", [f"F{i%3}"], [f"D{i%2}"]) for i in range(10)]
    model = _model(fps)
    for a in fps:
        for b in fps:
            score = cosine_similarity(a, b, model=model)
            assert 0.0 <= score <= 1.0 + 1e-9


def test_similarity_is_deterministic():
    fps = [_fp("A", ["F1"], ["D1"]), _fp("B", ["F1", "F2"], ["D1"])]
    model = _model(fps)
    first = cosine_similarity(fps[0], fps[1], model=model)
    second = cosine_similarity(fps[0], fps[1], model=model)
    assert first == second


def test_chains_with_no_shared_content_have_low_similarity():
    """No shared family/device/descriptor and different bins => near-zero, not 1.0."""
    small = ChainFingerprint(
        chain_id="A", lineage_component_id=None,
        family_terms=TermVector.from_terms(["F1"]),
        device_type_terms=TermVector.from_terms(["D1"]),
        descriptor_terms=(), size_bin=size_bin(1), duration_bin=duration_bin(5),
        member_count=1,
    )
    large = ChainFingerprint(
        chain_id="B", lineage_component_id=None,
        family_terms=TermVector.from_terms(["F2"]),
        device_type_terms=TermVector.from_terms(["D2"]),
        descriptor_terms=(), size_bin=size_bin(1000), duration_bin=duration_bin(50000),
        member_count=1000,
    )
    model = _model([small, large])
    score = cosine_similarity(small, large, model=model)
    assert score == 0.0


# --------------------------------------------------------------------------
# FingerprintModel versioning
# --------------------------------------------------------------------------


def test_idf_gives_more_weight_to_rare_terms():
    fps = [_fp("A", ["common"], []), _fp("B", ["common"], []), _fp("C", ["common", "rare"], [])]
    model = _model(fps)
    assert model.family_model.idf("rare") > model.family_model.idf("common")


def test_unseen_term_gets_max_weight_not_zero():
    """A term absent from the fit corpus must not vanish from later fingerprints."""
    model = _model([_fp("A", ["known"], [])])
    assert model.family_model.idf("never_seen") > 0.0


def test_scoring_across_model_versions_is_rejected():
    """A fingerprint stamped under sim-v1 must not silently score under sim-v2."""
    fps = [_fp("A", ["F1"], ["D1"]), _fp("B", ["F1"], ["D1"])]
    model_v1 = _model(fps, version="sim-v1")
    model_v2 = _model(fps, version="sim-v2")

    stamped = fps[0].scored_with(model_v1.model_version)
    with pytest.raises(ModelVersionMismatch):
        cosine_similarity(stamped, fps[1], model=model_v2)


def test_unstamped_fingerprint_scores_under_any_model():
    """A freshly built fingerprint has no prior model to conflict with."""
    fps = [_fp("A", ["F1"], ["D1"]), _fp("B", ["F1"], ["D1"])]
    model = _model(fps, version="sim-v2")
    # Neither fingerprint carries scored_with_model_version; must not raise.
    cosine_similarity(fps[0], fps[1], model=model)


def test_find_similar_chains_rejects_mismatched_corpus_entry():
    target = _fp("T", ["F1"], ["D1"], lineage="lc_1")
    other = _fp("O", ["F1"], ["D1"], lineage="lc_2")
    model_v1 = _model([target, other], version="sim-v1")
    model_v2 = _model([target, other], version="sim-v2")

    stamped_other = other.scored_with(model_v1.model_version)
    with pytest.raises(ModelVersionMismatch):
        find_similar_chains(target, [stamped_other], model=model_v2)


def test_snapshot_versioned_index_uses_history_strictly_before_cutoff():
    before = _fp("before", ["F1"], ["D1"])
    at_cutoff = _fp("at", ["F2"], ["D2"])
    future = _fp("future", ["F3"], ["D3"])

    index = materialize_similarity_index(
        [
            TimedChainFingerprint(future, "2026-08-29T10:01:00Z"),
            TimedChainFingerprint(at_cutoff, "2026-08-29T10:00:00Z"),
            TimedChainFingerprint(before, "2026-08-29T09:59:00Z"),
        ],
        model_version="sim-20260829-1000",
        trained_until_exclusive="2026-08-29T10:00:00Z",
        corpus_policy=CorpusPolicy.HISTORY_BEFORE_SNAPSHOT,
        model_update_policy=ModelUpdatePolicy.SNAPSHOT_VERSIONED,
        taxonomy_policy="TEST_EMPTY",
    )

    assert [entry.fingerprint.chain_id for entry in index.entries] == ["before"]
    assert index.model.trained_until_exclusive == "2026-08-29T10:00:00Z"
    assert index.model.corpus_policy == "HISTORY_BEFORE_SNAPSHOT"
    assert index.model.model_update_policy == "SNAPSHOT_VERSIONED"
    assert index.model.taxonomy_policy == "TEST_EMPTY"
    assert index.corpus[0].scored_with_model_version == "sim-20260829-1000"
    assert "family:F1" in index.model.vocabulary
    assert "family:F1" in index.model.idf_weights


def test_offline_frozen_model_never_uses_test_period():
    train = _fp("train", ["F1"], ["D1"])
    test = _fp("test", ["F2"], ["D2"])
    index = materialize_similarity_index(
        [
            TimedChainFingerprint(train, "2026-07-31T23:59:59Z"),
            TimedChainFingerprint(test, "2026-08-01T00:00:00Z"),
        ],
        model_version="benchmark-v1",
        trained_until_exclusive="2026-08-01T00:00:00Z",
        corpus_policy=CorpusPolicy.FROZEN_TRAINING,
        model_update_policy=ModelUpdatePolicy.FROZEN,
        taxonomy_policy="TEST_EMPTY",
    )

    assert [fingerprint.chain_id for fingerprint in index.corpus] == ["train"]
    assert "family:F2" not in index.model.vocabulary


# --------------------------------------------------------------------------
# Dedup by lineage_component_id
# --------------------------------------------------------------------------


def test_nearest_different_incident_excludes_same_lineage():
    """ADR-0022: cannot be the same lineage component as the target."""
    target = _fp("T", ["F1"], ["D1"], lineage="lc_1")
    same_lineage_other_snapshot = _fp("T_prev", ["F1"], ["D1"], lineage="lc_1")
    different_incident = _fp("O", ["F1"], ["D1"], lineage="lc_2")
    corpus = [target, same_lineage_other_snapshot, different_incident]

    model = _model(corpus)
    results = find_similar_chains(target, corpus, model=model, top_k=5)
    result_ids = {r.chain_id for r in results}
    assert "T_prev" not in result_ids
    assert "O" in result_ids


def test_target_itself_is_never_returned():
    target = _fp("T", ["F1"], ["D1"], lineage="lc_1")
    corpus = [target, _fp("O", ["F1"], ["D1"], lineage="lc_2")]
    model = _model(corpus)
    results = find_similar_chains(target, corpus, model=model)
    assert all(r.chain_id != "T" for r in results)


def test_results_are_sorted_by_similarity_descending():
    target = _fp("T", ["F1"], ["D1"], lineage="lc_1")
    corpus = [
        target,
        _fp("far", ["F9"], ["D9"], lineage="lc_2"),
        _fp("near", ["F1"], ["D1"], lineage="lc_3"),
    ]
    model = _model(corpus)
    results = find_similar_chains(target, corpus, model=model)
    assert results[0].chain_id == "near"


def test_equal_similarity_breaks_ties_deterministically_by_chain_id():
    """Same score, different lineage: ordering must not depend on corpus order."""
    target = _fp("T", ["F1"], ["D1"], lineage="lc_1")
    tie_b = _fp("B", ["F2"], ["D2"], lineage="lc_2")
    tie_z = _fp("Z", ["F2"], ["D2"], lineage="lc_3")
    corpus_order_1 = [target, tie_z, tie_b]
    corpus_order_2 = [target, tie_b, tie_z]

    model = _model(corpus_order_1)
    results_1 = find_similar_chains(target, corpus_order_1, model=model)
    results_2 = find_similar_chains(target, corpus_order_2, model=model)

    assert results_1[0].similarity == pytest.approx(results_1[1].similarity)
    # Regardless of corpus iteration order, "B" sorts before "Z" on tie.
    assert [r.chain_id for r in results_1] == [r.chain_id for r in results_2]
    assert results_1[0].chain_id == "B"


def test_no_lineage_id_means_no_exclusion_needed():
    """A chain with lineage_component_id=None cannot be dedup-matched against."""
    target = _fp("T", ["F1"], ["D1"], lineage=None)
    corpus = [target, _fp("O", ["F1"], ["D1"], lineage=None)]
    model = _model(corpus)
    results = find_similar_chains(target, corpus, model=model)
    assert any(r.chain_id == "O" for r in results)


def test_result_reports_compared_blocks():
    """UI diagnostic: which blocks actually contributed to this score."""
    target = build_fingerprint("T", [alarm("a1", device_type_name="STP")], lineage_component_id="lc_1")
    candidate = build_fingerprint("O", [alarm("a2", device_type_name="STP")], lineage_component_id="lc_2")
    model = _model([target, candidate])
    results = find_similar_chains(target, [target, candidate], model=model)
    assert results
    assert "device_type" in results[0].compared_blocks
    assert "alarm_taxonomy" not in results[0].compared_blocks


# --------------------------------------------------------------------------
# "Previous states of this chain" mode
# --------------------------------------------------------------------------


def test_previous_states_mode_returns_same_lineage_only():
    target = _fp("T", ["F1"], ["D1"], lineage="lc_1")
    same_lineage = _fp("T_prev", ["F1"], ["D1"], lineage="lc_1")
    different = _fp("O", ["F1"], ["D1"], lineage="lc_2")
    corpus = [target, same_lineage, different]
    model = _model(corpus)

    results = previous_states_of_chain(target, corpus, model=model)
    result_ids = {r.chain_id for r in results}
    assert result_ids == {"T_prev"}


def test_previous_states_mode_empty_without_lineage():
    target = _fp("T", ["F1"], ["D1"], lineage=None)
    corpus = [target, _fp("O", ["F1"], ["D1"], lineage=None)]
    model = _model(corpus)
    results = previous_states_of_chain(target, corpus, model=model)
    assert results == []


# --------------------------------------------------------------------------
# Real data
# --------------------------------------------------------------------------


@pytest.mark.realdata
def test_similar_chains_on_real_snapshot():
    import json
    import subprocess
    import sys

    from tests.conftest import MOCK_ROOT

    if not (MOCK_ROOT / "datasets/raw/alarm_data.csv").is_file():
        pytest.skip("real alarm export not present")
    venv = MOCK_ROOT / ".venv/bin/python"
    interpreter = str(venv) if venv.is_file() else sys.executable
    result = subprocess.run(
        [
            interpreter, "-m", "nocpro_mock.cli", "replay",
            "--limit", "800", "--snapshot-id", "s_similar_real",
        ],
        cwd=MOCK_ROOT, capture_output=True, text=True,
        env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"},
    )
    if result.returncode != 0:
        pytest.skip(f"mock CLI failed: {result.stderr[:300]}")

    from libs.contracts import load_package

    package = load_package(json.loads(result.stdout))
    fingerprints = [
        build_fingerprint(chain_id, package.alarms_of(chain_id), lineage_component_id=chain_id)
        for chain_id in package.chains
    ]
    assert len(fingerprints) == len(package.chains)

    model = fit_fingerprint_model(fingerprints, model_version="sim-real-v1")
    target = fingerprints[0]
    results = find_similar_chains(target, fingerprints, model=model, top_k=5)
    assert all(r.chain_id != target.chain_id for r in results)
    assert all(0.0 <= r.similarity <= 1.0 + 1e-9 for r in results)
    # Re-running must be deterministic.
    results_again = find_similar_chains(target, fingerprints, model=model, top_k=5)
    assert [r.chain_id for r in results] == [r.chain_id for r in results_again]

    # Real export: alarm_type_name is empty (verified), so any resolved
    # family term must be TYPE_FALLBACK only if alarm_type_name happens to be
    # non-empty; with this export it should simply be absent.
    if target.family_terms.counts:
        for key in target.family_terms.counts:
            assert key.startswith("FAMILY:") or key.startswith("TYPE_FALLBACK:")
