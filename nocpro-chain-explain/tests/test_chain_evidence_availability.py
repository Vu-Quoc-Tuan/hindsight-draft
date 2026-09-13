from __future__ import annotations

from types import SimpleNamespace

from nocpro_api.workspace import Workspace


def _analysis(*, fit=None):
    return SimpleNamespace(
        evidence=SimpleNamespace(statistics=SimpleNamespace(fits=fit or {})),
        graybox=SimpleNamespace(unavailable_capabilities=()),
    )


def test_chain_availability_is_fail_closed_without_models_or_channel_fit() -> None:
    workspace = Workspace()
    state = workspace.chain_evidence_availability(_analysis())

    assert state["historical"]["state"] == "UNAVAILABLE"
    assert state["temporal_delay"]["state"] == "UNAVAILABLE"
    assert state["topology"]["state"] == "UNAVAILABLE"
    assert state["dependency"]["state"] == "UNAVAILABLE"


def test_chain_availability_requires_an_attached_model_or_computable_fit() -> None:
    workspace = Workspace()
    workspace.historical_model = object()
    workspace.historical_taxonomy = object()
    workspace.temporal_delay_model = object()
    workspace.temporal_delay_taxonomy = object()
    available_fit = SimpleNamespace(unavailable_reason=None)

    state = workspace.chain_evidence_availability(
        _analysis(fit={("alarm-1", "Dep_hop"): available_fit})
    )

    assert state == {
        "historical": {"state": "AVAILABLE", "reason": None},
        "temporal_delay": {"state": "AVAILABLE", "reason": None},
        "topology": {"state": "AVAILABLE", "reason": None},
        "dependency": {"state": "AVAILABLE", "reason": None},
    }
