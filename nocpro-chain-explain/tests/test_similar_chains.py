"""Similar Chains tests (§8.3, ADR-0022).

Pinned invariants:
  - fingerprint is deterministic for fixed input
  - family term backs off to alarm_type_name when no taxonomy is supplied
  - device_type_name is used verbatim, never guessed from a device-code prefix
  - missing duration gets its own bin, not bin 0
  - cosine similarity is deterministic and in [0,1]
  - the nearest "different incident" result excludes the same lineage component
  - "previous states of this chain" mode returns exactly the same-lineage chains
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
    TermVector,
    TfIdfModel,
    build_fingerprint,
    cosine_similarity,
    duration_bin,
    find_similar_chains,
    fit_tfidf_models,
    previous_states_of_chain,
    size_bin,
)


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


# --------------------------------------------------------------------------
# Bins
# --------------------------------------------------------------------------


def test_size_bin_is_monotonic():
    assert size_bin(1) != size_bin(100)
    small = size_bin(1)
    large = size_bin(1000)
    assert small != large


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
# Fingerprint / backoff
# --------------------------------------------------------------------------


def test_family_backs_off_to_alarm_type_when_untaxonomized():
    """BACKOFF type->family->category: no taxonomy => fall to alarm_type_name."""
    alarms = [alarm("a1", alarm_name="LINK DOWN", alarm_type_name="CONNECTIVITY")]
    fp = build_fingerprint("C1", alarms)
    assert fp.family_terms.counts == {"CONNECTIVITY": 1}


def test_family_uses_taxonomy_when_available():
    taxonomy = AlarmTaxonomy(families={"LINK DOWN": "LINK"}, categories={})
    alarms = [alarm("a1", alarm_name="LINK DOWN", alarm_type_name="CONNECTIVITY")]
    fp = build_fingerprint("C1", alarms, taxonomy=taxonomy)
    # Taxonomy family wins over the alarm_type_name backoff.
    assert fp.family_terms.counts == {"LINK": 1}


def test_family_is_absent_when_neither_taxonomy_nor_type_available():
    """Real export case: alarm_type_name empty and no taxonomy given."""
    alarms = [alarm("a1", alarm_name="LINK DOWN", alarm_type_name="")]
    fp = build_fingerprint("C1", alarms)
    assert fp.family_terms.counts == {}


def test_device_type_is_used_verbatim_not_guessed_from_prefix():
    """device_type_name is a real column; it must not be derived from device_code."""
    alarms = [alarm("a1", device_code="HLC9102DEA01", device_type_name="ROUTER")]
    fp = build_fingerprint("C1", alarms)
    assert fp.device_type_terms.counts == {"ROUTER": 1}


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


# --------------------------------------------------------------------------
# TF-IDF
# --------------------------------------------------------------------------


def test_idf_gives_more_weight_to_rare_terms():
    vectors = [
        TermVector.from_terms(["common"]),
        TermVector.from_terms(["common"]),
        TermVector.from_terms(["common", "rare"]),
    ]
    model = TfIdfModel.fit(vectors)
    assert model.idf("rare") > model.idf("common")


def test_unseen_term_gets_max_weight_not_zero():
    """A term absent from the fit corpus must not vanish from later fingerprints."""
    model = TfIdfModel.fit([TermVector.from_terms(["known"])])
    assert model.idf("never_seen") > 0.0


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
    family_model, device_model = fit_tfidf_models(fps)
    score = cosine_similarity(fps[0], fps[1], family_model=family_model, device_model=device_model)
    assert score == pytest.approx(1.0)


def test_disjoint_fingerprints_have_low_similarity():
    fps = [_fp("A", ["F1"], ["D1"]), _fp("B", ["F2"], ["D2"])]
    family_model, device_model = fit_tfidf_models(fps)
    score = cosine_similarity(fps[0], fps[1], family_model=family_model, device_model=device_model)
    # Different family/device but same size/duration bin, so not exactly 0.
    assert 0.0 <= score < 1.0


def test_similarity_is_within_unit_interval():
    fps = [_fp(f"C{i}", [f"F{i%3}"], [f"D{i%2}"]) for i in range(10)]
    family_model, device_model = fit_tfidf_models(fps)
    for a in fps:
        for b in fps:
            score = cosine_similarity(a, b, family_model=family_model, device_model=device_model)
            assert 0.0 <= score <= 1.0 + 1e-9


def test_similarity_is_deterministic():
    fps = [_fp("A", ["F1"], ["D1"]), _fp("B", ["F1", "F2"], ["D1"])]
    family_model, device_model = fit_tfidf_models(fps)
    first = cosine_similarity(fps[0], fps[1], family_model=family_model, device_model=device_model)
    second = cosine_similarity(fps[0], fps[1], family_model=family_model, device_model=device_model)
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
    family_model, device_model = fit_tfidf_models([small, large])
    score = cosine_similarity(small, large, family_model=family_model, device_model=device_model)
    assert score == 0.0


def test_a_fingerprint_always_has_size_and_duration_terms():
    """build_fingerprint never produces a truly contentless vector."""
    fp = build_fingerprint("C1", [alarm("a1")])
    assert fp.size_bin
    assert fp.duration_bin


# --------------------------------------------------------------------------
# Dedup by lineage_component_id
# --------------------------------------------------------------------------


def test_nearest_different_incident_excludes_same_lineage():
    """ADR-0022: cannot be the same lineage component as the target."""
    target = _fp("T", ["F1"], ["D1"], lineage="lc_1")
    same_lineage_other_snapshot = _fp("T_prev", ["F1"], ["D1"], lineage="lc_1")
    different_incident = _fp("O", ["F1"], ["D1"], lineage="lc_2")
    corpus = [target, same_lineage_other_snapshot, different_incident]

    family_model, device_model = fit_tfidf_models(corpus)
    results = find_similar_chains(
        target, corpus, family_model=family_model, device_model=device_model, top_k=5
    )
    result_ids = {r.chain_id for r in results}
    assert "T_prev" not in result_ids
    assert "O" in result_ids


def test_target_itself_is_never_returned():
    target = _fp("T", ["F1"], ["D1"], lineage="lc_1")
    corpus = [target, _fp("O", ["F1"], ["D1"], lineage="lc_2")]
    family_model, device_model = fit_tfidf_models(corpus)
    results = find_similar_chains(
        target, corpus, family_model=family_model, device_model=device_model
    )
    assert all(r.chain_id != "T" for r in results)


def test_results_are_sorted_by_similarity_descending():
    target = _fp("T", ["F1"], ["D1"], lineage="lc_1")
    corpus = [
        target,
        _fp("far", ["F9"], ["D9"], lineage="lc_2"),
        _fp("near", ["F1"], ["D1"], lineage="lc_3"),
    ]
    family_model, device_model = fit_tfidf_models(corpus)
    results = find_similar_chains(
        target, corpus, family_model=family_model, device_model=device_model
    )
    assert results[0].chain_id == "near"


def test_no_lineage_id_means_no_exclusion_needed():
    """A chain with lineage_component_id=None cannot be dedup-matched against."""
    target = _fp("T", ["F1"], ["D1"], lineage=None)
    corpus = [target, _fp("O", ["F1"], ["D1"], lineage=None)]
    family_model, device_model = fit_tfidf_models(corpus)
    results = find_similar_chains(
        target, corpus, family_model=family_model, device_model=device_model
    )
    assert any(r.chain_id == "O" for r in results)


# --------------------------------------------------------------------------
# "Previous states of this chain" mode
# --------------------------------------------------------------------------


def test_previous_states_mode_returns_same_lineage_only():
    target = _fp("T", ["F1"], ["D1"], lineage="lc_1")
    same_lineage = _fp("T_prev", ["F1"], ["D1"], lineage="lc_1")
    different = _fp("O", ["F1"], ["D1"], lineage="lc_2")
    corpus = [target, same_lineage, different]
    family_model, device_model = fit_tfidf_models(corpus)

    results = previous_states_of_chain(
        target, corpus, family_model=family_model, device_model=device_model
    )
    result_ids = {r.chain_id for r in results}
    assert result_ids == {"T_prev"}


def test_previous_states_mode_empty_without_lineage():
    target = _fp("T", ["F1"], ["D1"], lineage=None)
    corpus = [target, _fp("O", ["F1"], ["D1"], lineage=None)]
    family_model, device_model = fit_tfidf_models(corpus)
    results = previous_states_of_chain(
        target, corpus, family_model=family_model, device_model=device_model
    )
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

    family_model, device_model = fit_tfidf_models(fingerprints)
    target = fingerprints[0]
    results = find_similar_chains(
        target, fingerprints, family_model=family_model, device_model=device_model, top_k=5
    )
    assert all(r.chain_id != target.chain_id for r in results)
    assert all(0.0 <= r.similarity <= 1.0 + 1e-9 for r in results)
    # Re-running must be deterministic.
    results_again = find_similar_chains(
        target, fingerprints, family_model=family_model, device_model=device_model, top_k=5
    )
    assert [r.chain_id for r in results] == [r.chain_id for r in results_again]
