from types import SimpleNamespace

from nocpro_api.routes import _build_persisted_quality_summaries


def row(**values):
    return SimpleNamespace(**values)


def test_quality_summary_separates_persisted_running_waiting_and_singletons():
    chains = [
        row(snapshot_id="S1", snapshot_version="v1", chain_id="strong", member_count=4, chain_name="Strong", event_span_seconds=40),
        row(snapshot_id="S1", snapshot_version="v1", chain_id="review", member_count=3, chain_name="Review", event_span_seconds=30),
        row(snapshot_id="S1", snapshot_version="v1", chain_id="running", member_count=2, chain_name="Running", event_span_seconds=20),
        row(snapshot_id="S1", snapshot_version="v1", chain_id="waiting", member_count=5, chain_name="Waiting", event_span_seconds=50),
        row(snapshot_id="S1", snapshot_version="v1", chain_id="singleton", member_count=1, chain_name="Singleton", event_span_seconds=10),
    ]
    assessments = [
        row(snapshot_id="S1", snapshot_version="v1", chain_id="strong", payload={
            "status": "EVALUATED", "stars": 4,
            "overview_projection": {
                "projection_version": "CHAIN_OVERVIEW_V3",
                "pipeline_version": "DETERMINISTIC_QUALITY_V3",
                "config_version": "v1",
            },
        }),
        row(snapshot_id="S1", snapshot_version="v1", chain_id="review", payload={
            "status": "EVALUATED", "stars": 2,
            "overview_projection": {
                "projection_version": "CHAIN_OVERVIEW_V3",
                "pipeline_version": "DETERMINISTIC_QUALITY_V3",
                "config_version": "v1",
            },
        }),
    ]
    jobs = [row(
        snapshot_id="S1",
        snapshot_version="v1",
        chain_id="running",
        analysis_config_version="v1|p2:fixture",
    )]

    summary = _build_persisted_quality_summaries(
        chains,
        assessments,
        jobs,
        expected_config_version="v1",
    )[0]

    assert summary.total_chain_count == 5
    assert summary.eligible_chain_count == 4
    assert summary.sturdy_count == 1
    assert summary.review_count == 1
    assert summary.evaluating_count == 1
    assert summary.unevaluated_count == 1
    assert summary.not_applicable_count == 1
    assert summary.star_counts == {"1": 0, "2": 1, "3": 0, "4": 1, "5": 0}
    assert [item.chain_id for item in summary.attention_chains] == ["review", "running", "waiting"]
    assert summary.attention_chains[0].status == "REVIEW"
    assert {item.chain_id: (item.status, item.stars) for item in summary.chain_assessments} == {
        "review": ("REVIEW", 2),
        "running": ("EVALUATING", None),
        "singleton": ("NOT_APPLICABLE", None),
        "strong": ("EVALUATED", 4),
        "waiting": ("WAITING", None),
    }


def test_persisted_result_wins_over_an_active_job_for_same_chain():
    chains = [row(snapshot_id="S1", snapshot_version="v1", chain_id="done", member_count=2, chain_name="Done", event_span_seconds=20)]
    assessments = [row(
        snapshot_id="S1",
        snapshot_version="v1",
        chain_id="done",
        payload={
            "status": "EVALUATED",
            "stars": 5,
            "overview_projection": {
                "config_version": "v1",
                "projection_version": "CHAIN_OVERVIEW_V3",
                "pipeline_version": "DETERMINISTIC_QUALITY_V3",
            },
        },
    )]
    jobs = [row(
        snapshot_id="S1",
        snapshot_version="v1",
        chain_id="done",
        analysis_config_version="v1|p2:fixture",
    )]

    summary = _build_persisted_quality_summaries(chains, assessments, jobs)[0]

    assert summary.sturdy_count == 1
    assert summary.evaluating_count == 0
    assert summary.unevaluated_count == 0

    stale_summary = _build_persisted_quality_summaries(
        chains,
        assessments,
        jobs,
        expected_config_version="v2",
    )[0]
    stale_chain = stale_summary.chain_assessments[0]
    assert stale_summary.sturdy_count == 0
    assert stale_summary.unevaluated_count == 1
    assert stale_chain.status == "WAITING"
    assert stale_chain.stars is None


def test_stale_active_job_does_not_mask_waiting_quality_result():
    chains = [row(
        snapshot_id="S1",
        snapshot_version="v1",
        chain_id="done",
        member_count=2,
        chain_name="Done",
        event_span_seconds=20,
    )]
    assessments = [row(
        snapshot_id="S1",
        snapshot_version="v1",
        chain_id="done",
        payload={"status": "EVALUATED", "stars": 4},
    )]
    jobs = [row(
        snapshot_id="S1",
        snapshot_version="v1",
        chain_id="done",
        analysis_config_version="v1|p2:fixture",
    )]

    summary = _build_persisted_quality_summaries(
        chains,
        assessments,
        jobs,
        expected_config_version="v2",
    )[0]

    assert summary.evaluating_count == 0
    assert summary.unevaluated_count == 1
    assert summary.chain_assessments[0].status == "WAITING"


def test_unavailable_result_is_terminal_and_not_waiting():
    chains = [
        row(snapshot_id="S1", snapshot_version="v1", chain_id="missing", member_count=2, chain_name="Missing", event_span_seconds=20),
        row(snapshot_id="S1", snapshot_version="v1", chain_id="waiting", member_count=2, chain_name="Waiting", event_span_seconds=20),
    ]
    assessments = [
        row(
            snapshot_id="S1",
            snapshot_version="v1",
            chain_id="missing",
            payload={
                "status": "UNAVAILABLE",
                "stars": None,
                "label": "Chưa thể chấm",
                "reasons": ["Chưa đủ thành viên có evidence để đánh giá vai trò."],
                "overview_projection": {
                    "config_version": "v1",
                    "projection_version": "CHAIN_OVERVIEW_V3",
                    "pipeline_version": "DETERMINISTIC_QUALITY_V3",
                },
            },
        )
    ]

    summary = _build_persisted_quality_summaries(chains, assessments, [])[0]

    assert summary.unavailable_count == 1
    assert summary.evaluating_count == 0
    assert summary.unevaluated_count == 1
    assert [(item.chain_id, item.status) for item in summary.attention_chains] == [
        ("missing", "UNAVAILABLE"),
        ("waiting", "WAITING"),
    ]

    stale_summary = _build_persisted_quality_summaries(
        chains,
        assessments,
        [],
        expected_config_version="v2",
    )[0]
    assert stale_summary.unavailable_count == 0
    assert stale_summary.unevaluated_count == 2
    assert {item.chain_id: (item.status, item.stars) for item in stale_summary.chain_assessments} == {
        "missing": ("WAITING", None),
        "waiting": ("WAITING", None),
    }
