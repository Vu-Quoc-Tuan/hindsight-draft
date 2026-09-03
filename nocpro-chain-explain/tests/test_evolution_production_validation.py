"""Production validation must not be inferred from a derived replay sequence."""

from __future__ import annotations

from types import SimpleNamespace

from nocpro_api.persistence.repository import _sequence_production_validation


def test_derived_replay_sequence_is_never_production_eligible() -> None:
    snapshots = [
        SimpleNamespace(
            source_kind="REAL_EXPORT_REPLAY",
            source="nocpro-mock-derived-replay-slicer",
        ),
        SimpleNamespace(
            source_kind="REAL_EXPORT_REPLAY",
            source="nocpro-mock-derived-replay-slicer",
        ),
    ]
    assert _sequence_production_validation(snapshots) == "NOT_ESTABLISHED"


def test_verified_real_sources_remain_eligible_at_this_projection_layer() -> None:
    snapshots = [
        SimpleNamespace(source_kind="REAL_EXPORT_REPLAY", source="nocpro-upstream"),
        SimpleNamespace(source_kind="REAL_LIVE", source="nocpro-upstream"),
    ]
    assert _sequence_production_validation(snapshots) == "ELIGIBLE"
