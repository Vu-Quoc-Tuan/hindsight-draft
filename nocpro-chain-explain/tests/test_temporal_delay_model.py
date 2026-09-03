from history import TaxonomyLevel, TaxonomyTokens
from temporal_delay import DelayEstimator, DelayModelConfig, DelayObservation, DelayRelationKey, build_delay_model, evaluate_delay_model, evaluate_delay_model_oracle, evaluate_ordered_delay_model, model_from_dict, model_to_dict


def config():
    return DelayModelConfig("delay-synthetic-v1", 2, 4, 0.4, 42, (2.0, 5.0), (2.0, 5.0), (1.0, 3.0), DelayEstimator.HISTOGRAM, 5.0, fallback_histogram_bin_width_seconds=5.0)


def observation(episode: str, source: str, target: str, delay: float, *, reverse: bool = False):
    left, right = ("B", "A") if reverse else ("A", "B")
    return DelayObservation(episode, source, target, DelayRelationKey(TaxonomyLevel.TYPE, left, right), delay)


def test_snapshot_dedup_and_episode_balancing_are_relation_local():
    model = build_delay_model(
        [observation("e1", "a", "b", 2), observation("e1", "a", "b", 2), observation("e1", "a2", "b2", 3), observation("e2", "a3", "b3", 100)],
        training_cutoff="2026-01-02T00:00:00Z", lineage_prefix_fingerprint="prefix", taxonomy_source_id="syn", taxonomy_source_version="v1", config=config(),
    )
    relation = model.relations[DelayRelationKey(TaxonomyLevel.TYPE, "A", "B")]
    assert relation.raw_observation_count == 3
    assert relation.episode_sample_count == 2
    assert relation.effective_weight == 2
    assert relation.typicality(2) > relation.typicality(50)


def test_direction_is_ordered_and_selected_model_is_deterministic():
    samples = [observation(f"e{i}", f"a{i}", f"b{i}", 2 if i % 2 else 100) for i in range(6)]
    samples.append(observation("reverse", "b", "a", 7, reverse=True))
    first = build_delay_model(samples, training_cutoff="2026-01-02T00:00:00Z", lineage_prefix_fingerprint="prefix", taxonomy_source_id="syn", taxonomy_source_version="v1", config=config())
    second = build_delay_model(reversed(samples), training_cutoff="2026-01-02T00:00:00Z", lineage_prefix_fingerprint="prefix", taxonomy_source_id="syn", taxonomy_source_version="v1", config=config())
    assert DelayRelationKey(TaxonomyLevel.TYPE, "B", "A") not in first.relations
    assert first == second
    assert first.relations[DelayRelationKey(TaxonomyLevel.TYPE, "A", "B")].selection_mode == "HELD_OUT_SELECTED"


def test_runtime_uses_first_usable_common_level_not_better_coarse_score():
    samples = [observation(f"e{i}", f"a{i}", f"b{i}", 2) for i in range(4)]
    model = build_delay_model(samples, training_cutoff="2026-01-02T00:00:00Z", lineage_prefix_fingerprint="prefix", taxonomy_source_id="syn", taxonomy_source_version="v1", config=config())
    result = evaluate_delay_model(TaxonomyTokens(type="A", family="FA"), TaxonomyTokens(type="B", family="FB"), delay_seconds=50, model=model)
    assert result.available is True
    assert result.resolved_level is TaxonomyLevel.TYPE
    assert result.positive_score == 0
    reverse = evaluate_delay_model(TaxonomyTokens(type="B"), TaxonomyTokens(type="A"), delay_seconds=2, model=model)
    assert reverse.available is False
    assert reverse.reason == "INSUFFICIENT_TEMPORAL_HISTORY"
    assert reverse.backoff_reason == "INSUFFICIENT_TYPE_TEMPORAL_HISTORY"


def test_runtime_and_oracle_keep_the_same_frozen_relation_result():
    samples = [observation(f"e{i}", f"a{i}", f"b{i}", 2 if i % 2 else 100) for i in range(6)]
    frozen = build_delay_model(samples, training_cutoff="2026-01-02T00:00:00Z", lineage_prefix_fingerprint="prefix", taxonomy_source_id="syn", taxonomy_source_version="v1", config=config())
    runtime = evaluate_delay_model(TaxonomyTokens(type="A"), TaxonomyTokens(type="B"), delay_seconds=50, model=frozen)
    oracle = evaluate_delay_model_oracle(TaxonomyTokens(type="A"), TaxonomyTokens(type="B"), delay_seconds=50, observations=samples, training_cutoff=frozen.training_cutoff, lineage_prefix_fingerprint="prefix", taxonomy_source_id="syn", taxonomy_source_version="v1", config=config())
    assert runtime == oracle
    assert runtime.relation is not None
    assert runtime.relation.raw_observation_count == 6
    assert runtime.relation.episode_sample_count == 6


def test_equal_current_timestamps_are_not_directed_temporal_evidence():
    result = evaluate_ordered_delay_model(TaxonomyTokens(type="A"), TaxonomyTokens(type="B"), left_start="2026-01-01T00:00:00Z", right_start="2026-01-01T00:00:00Z", model=None)
    assert result.available is False
    assert result.reason == "NO_DIRECTED_TEMPORAL_ORDER"


def test_runtime_reverses_relation_only_when_current_order_reverses():
    samples = [observation(f"e{i}", f"a{i}", f"b{i}", 5) for i in range(4)]
    model = build_delay_model(samples, training_cutoff="2026-01-02T00:00:00Z", lineage_prefix_fingerprint="prefix", taxonomy_source_id="syn", taxonomy_source_version="v1", config=config())
    forward = evaluate_ordered_delay_model(TaxonomyTokens(type="A"), TaxonomyTokens(type="B"), left_start="2026-01-01T00:00:00Z", right_start="2026-01-01T00:00:05Z", model=model)
    backward = evaluate_ordered_delay_model(TaxonomyTokens(type="A"), TaxonomyTokens(type="B"), left_start="2026-01-01T00:00:05Z", right_start="2026-01-01T00:00:00Z", model=model)
    assert forward.available is True
    assert forward.relation_key == DelayRelationKey(TaxonomyLevel.TYPE, "A", "B")
    assert backward.available is False
    assert backward.reason == "INSUFFICIENT_TEMPORAL_HISTORY"
    assert backward.backoff_reason == "INSUFFICIENT_TYPE_TEMPORAL_HISTORY"


def test_missing_fallback_is_relation_unavailable_not_global_build_failure():
    broken = DelayModelConfig("delay-broken", 2, 4, 0.4, 42, (2.0,), (2.0,), (1.0,), DelayEstimator.HISTOGRAM, 2.0)
    selected = [observation(f"selected-{i}", f"a{i}", f"b{i}", 2) for i in range(6)]
    fallback = [DelayObservation(f"fallback-{i}", f"c{i}", f"d{i}", DelayRelationKey(TaxonomyLevel.TYPE, "C", "D"), 3) for i in range(2)]
    model = build_delay_model([*selected, *fallback], training_cutoff="2026-01-02T00:00:00Z", lineage_prefix_fingerprint="prefix", taxonomy_source_id="syn", taxonomy_source_version="v1", config=broken)
    assert DelayRelationKey(TaxonomyLevel.TYPE, "A", "B") in model.relations
    failed = evaluate_delay_model(TaxonomyTokens(type="C", family="FC"), TaxonomyTokens(type="D", family="FD"), delay_seconds=3, model=model)
    assert failed.available is False
    assert failed.reason == "TEMPORAL_DELAY_CONFIG_INCOMPLETE"


def test_held_out_split_is_episode_isolated_and_order_independent():
    samples = [observation("storm", f"a{i}", f"b{i}", 2 + i) for i in range(4)] + [observation(f"e{i}", f"x{i}", f"y{i}", 100) for i in range(1, 7)]
    first = build_delay_model(samples, training_cutoff="2026-01-02T00:00:00Z", lineage_prefix_fingerprint="prefix", taxonomy_source_id="syn", taxonomy_source_version="v1", config=config())
    second = build_delay_model(reversed(samples), training_cutoff="2026-01-02T00:00:00Z", lineage_prefix_fingerprint="prefix", taxonomy_source_id="syn", taxonomy_source_version="v1", config=config())
    relation = first.relations[DelayRelationKey(TaxonomyLevel.TYPE, "A", "B")]
    assert set(relation.train_episode_ids).isdisjoint(relation.holdout_episode_ids)
    assert "storm" in set(relation.train_episode_ids) | set(relation.holdout_episode_ids)
    assert first == second


def test_common_level_backoff_only_after_insufficient_history():
    type_key = DelayRelationKey(TaxonomyLevel.TYPE, "A", "B")
    family_key = DelayRelationKey(TaxonomyLevel.FAMILY, "FA", "FB")
    category_key = DelayRelationKey(TaxonomyLevel.CATEGORY, "CA", "CB")
    samples = [DelayObservation("type-only", "a", "b", type_key, 50)]
    samples += [DelayObservation(f"family-{i}", f"fa{i}", f"fb{i}", family_key, 2) for i in range(2)]
    samples += [DelayObservation(f"category-{i}", f"ca{i}", f"cb{i}", category_key, 100) for i in range(2)]
    model = build_delay_model(samples, training_cutoff="2026-01-02T00:00:00Z", lineage_prefix_fingerprint="prefix", taxonomy_source_id="syn", taxonomy_source_version="v1", config=config())
    lookup = evaluate_delay_model(TaxonomyTokens(type="A", family="FA", category="CA"), TaxonomyTokens(type="B", family="FB", category="CB"), delay_seconds=2, model=model)
    assert lookup.available is True
    assert lookup.resolved_level is TaxonomyLevel.FAMILY
    assert lookup.relation_key == family_key
    assert lookup.backoff_reason == "INSUFFICIENT_TYPE_TEMPORAL_HISTORY"


def test_bimodal_local_mass_never_uses_cdf_midpoint_centrality():
    samples = [observation(f"low-{i}", f"la{i}", f"lb{i}", value) for i, value in enumerate((2, 2, 3))]
    samples += [observation(f"high-{i}", f"ha{i}", f"hb{i}", value) for i, value in enumerate((99, 100, 101))]
    model = build_delay_model(samples, training_cutoff="2026-01-02T00:00:00Z", lineage_prefix_fingerprint="prefix", taxonomy_source_id="syn", taxonomy_source_version="v1", config=config())
    relation = model.relations[DelayRelationKey(TaxonomyLevel.TYPE, "A", "B")]
    assert relation.typicality(2) > 0.9
    assert relation.typicality(100) > 0.9
    assert relation.typicality(50) < 0.1


def test_insufficient_all_levels_and_missing_taxonomy_are_unavailable():
    model = build_delay_model([observation("only", "a", "b", 2)], training_cutoff="2026-01-02T00:00:00Z", lineage_prefix_fingerprint="prefix", taxonomy_source_id="syn", taxonomy_source_version="v1", config=config())
    insufficient = evaluate_delay_model(TaxonomyTokens(type="A", family="FA", category="CA"), TaxonomyTokens(type="B", family="FB", category="CB"), delay_seconds=2, model=model)
    missing = evaluate_delay_model(None, TaxonomyTokens(type="B"), delay_seconds=2, model=model)
    assert insufficient.available is False
    assert insufficient.reason == "INSUFFICIENT_TEMPORAL_HISTORY"
    assert insufficient.backoff_reason == "INSUFFICIENT_CATEGORY_TEMPORAL_HISTORY"
    assert missing.reason == "TAXONOMY_UNAVAILABLE"


def test_model_round_trip_preserves_frozen_score_and_provenance():
    model = build_delay_model([observation(f"e{i}", f"a{i}", f"b{i}", 2) for i in range(4)], training_cutoff="2026-01-02T00:00:00Z", lineage_prefix_fingerprint="prefix", taxonomy_source_id="syn", taxonomy_source_version="v1", config=config())
    restored = model_from_dict(model_to_dict(model))
    assert restored == model
    assert evaluate_delay_model(TaxonomyTokens(type="A"), TaxonomyTokens(type="B"), delay_seconds=2, model=restored) == evaluate_delay_model(TaxonomyTokens(type="A"), TaxonomyTokens(type="B"), delay_seconds=2, model=model)
