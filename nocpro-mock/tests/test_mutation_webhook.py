"""Unit tests for mutation webhook dispatcher."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
import urllib.error

from nocpro_mock.producer.mutation_webhook import MutationEvent, dispatch_mutation


def _event() -> MutationEvent:
    return MutationEvent(
        event_id="evt-1",
        chain_id="C1",
        operation="SPLIT_CHAIN",
        candidate_id="cand-split-1",
        partition_delta={"before": [["C1", ["A1", "A2"]]], "after": [["C1", ["A1"]], ["C2", ["A2"]]]},
        operator_id="operator_01",
        approved_at="2026-09-04T00:00:00Z",
        reason="Split confirmed by engineer",
    )


def test_dispatch_without_webhook_url_records_audit_log() -> None:
    event = _event()
    result = dispatch_mutation(event, webhook_url=None)
    assert result["dispatched"] is False
    assert result["reason"] == "WEBHOOK_NOT_CONFIGURED"
    assert result["event_id"] == "evt-1"
    assert result["payload"]["chain_id"] == "C1"
    assert result["payload"]["operation"] == "SPLIT_CHAIN"


def test_dispatch_successful_http_call() -> None:
    event = _event()
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.__enter__.return_value = mock_response

    with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
        result = dispatch_mutation(event, webhook_url="http://nocpro-upstream.internal/api/webhook/mutation")
        assert result["dispatched"] is True
        assert result["status_code"] == 200
        assert result["event_id"] == "evt-1"

        # Verify request payload
        req = mock_urlopen.call_args[0][0]
        assert req.full_url == "http://nocpro-upstream.internal/api/webhook/mutation"
        assert req.get_method() == "POST"
        body = json.loads(req.data.decode("utf-8"))
        assert body["event_id"] == "evt-1"
        assert body["operation"] == "SPLIT_CHAIN"


def test_dispatch_handles_http_error() -> None:
    event = _event()
    http_error = urllib.error.HTTPError(
        url="http://nocpro-upstream.internal/api/webhook/mutation",
        code=502,
        msg="Bad Gateway",
        hdrs={},
        fp=None,
    )

    with patch("urllib.request.urlopen", side_effect=http_error):
        result = dispatch_mutation(event, webhook_url="http://nocpro-upstream.internal/api/webhook/mutation")
        assert result["dispatched"] is False
        assert result["status_code"] == 502
        assert "502" in result["error"]


def test_dispatch_handles_network_failure() -> None:
    event = _event()
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
        result = dispatch_mutation(event, webhook_url="http://invalid.local/webhook")
        assert result["dispatched"] is False
        assert "Connection refused" in result["error"]
