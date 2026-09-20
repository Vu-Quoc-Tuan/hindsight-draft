from review_learning import (
    FEATURE_NAMES,
    features_to_vector,
    materialize_candidate_features,
)


def test_feature_vector_is_deterministic_and_matches_names():
    deterministic_ctx = {
        "metric_deltas": {
            "weak_member_count": -2.0,
            "minimum_membership_support": 0.25,
            "evidence_union_coverage": 0.10,
        },
        "before_metrics": {
            "weak_member_count": {"availability": "AVAILABLE", "value": 3.0},
        },
        "edit_cost": {"members_moved": 2},
    }
    f1 = materialize_candidate_features(
        operation="MOVE_MEMBER",
        deterministic_context=deterministic_ctx,
        hard_gate_status="PASSED",
        pareto_state="FRONTIER_SELECTED",
        source_kind="REAL_LIVE",
    )
    f2 = materialize_candidate_features(
        operation="MOVE_MEMBER",
        deterministic_context=deterministic_ctx,
        hard_gate_status="PASSED",
        pareto_state="FRONTIER_SELECTED",
        source_kind="REAL_LIVE",
    )
    assert f1 == f2
    assert len(f1) == len(FEATURE_NAMES)

    vec = features_to_vector(f1)
    assert len(vec) == len(FEATURE_NAMES)
    assert all(isinstance(v, float) for v in vec)


def test_no_raw_ids_in_feature_names_or_values():
    raw_forbidden = ["alarm_id", "chain_id", "snapshot_id", "reviewer_id", "device_code"]
    for name in FEATURE_NAMES:
        for forbidden in raw_forbidden:
            assert forbidden not in name


def test_missing_features_have_zero_availability_indicator():
    f = materialize_candidate_features(
        operation="REMOVE_MEMBER",
        deterministic_context={},
        temporal_context={"status": "UNAVAILABLE"},
        case_context={"status": "UNAVAILABLE"},
    )
    assert f["temporal__delay_score_mean__available"] == 0.0
    assert f["temporal__atypical_fraction__available"] == 0.0
    assert f["similar_cases__approved_ratio__available"] == 0.0
    assert f["delta__weak_member_count__available"] == 0.0


def test_operation_one_hot_is_exact():
    f_remove = materialize_candidate_features(operation="REMOVE_MEMBER")
    assert f_remove["op__remove"] == 1.0
    assert f_remove["op__split"] == 0.0
    assert f_remove["op__move"] == 0.0
    assert f_remove["op__merge"] == 0.0

    f_split = materialize_candidate_features(operation="SPLIT_CHAIN")
    assert f_split["op__remove"] == 0.0
    assert f_split["op__split"] == 1.0
