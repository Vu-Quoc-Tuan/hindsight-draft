"""Tests for the optional ADR-0024 grounded narrative provider."""

from __future__ import annotations

import json
import logging
import urllib.error
from typing import Any

import pytest

from nocpro_api.grounded_llm import render_grounded


class _Response:
    def __init__(self, payload: dict[str, Any] | bytes) -> None:
        self._payload = (
            payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        )

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int | None = None) -> bytes:
        return self._payload


def _configure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_API_KEY", "test-secret")
    monkeypatch.setenv("AI_BASE_URL", "https://provider.invalid/v1")
    monkeypatch.setenv("AI_MODEL", "test-model")


def test_renderer_uses_configured_provider_with_bounded_grounded_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    captured: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: float) -> _Response:
        captured["url"] = request.full_url
        captured["authorization"] = request.get_header("Authorization")
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _Response({"choices": [{"message": {"content": "Rendered grounded text"}}]})

    monkeypatch.setattr("nocpro_api.grounded_llm.urllib.request.urlopen", fake_urlopen)
    result = render_grounded(
        draft="Deterministic draft",
        facts={"status": "AVAILABLE", "member_count": 2},
        fact_refs=["analysis:C1"],
        purpose="ADVISOR",
    )

    assert result.message == "Rendered grounded text"
    assert result.model == "test-model"
    assert result.provider_status == "OK"
    assert result.used_provider is True
    assert captured["url"] == "https://provider.invalid/v1/chat/completions"
    assert captured["authorization"] == "Bearer test-secret"
    assert captured["timeout"] == 8.0
    body_text = json.dumps(captured["body"])
    assert "Deterministic draft" in body_text
    assert "analysis:C1" in body_text
    assert "test-secret" not in body_text


def test_renderer_uses_native_ollama_chat_protocol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    monkeypatch.setenv("AI_PROVIDER_PROTOCOL", "OLLAMA")
    monkeypatch.setenv("AI_BASE_URL", "https://ollama.com/api")
    monkeypatch.setenv("AI_MODEL", "gpt-oss:120b")
    captured: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: float) -> _Response:
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _Response(
            {
                "model": "gpt-oss:120b",
                "message": {
                    "role": "assistant",
                    "content": "Grounded Ollama text",
                    "thinking": "This field must never become the narrative.",
                    "tool_calls": [{"function": {"name": "forbidden"}}],
                },
                "done": True,
            }
        )

    monkeypatch.setattr("nocpro_api.grounded_llm.urllib.request.urlopen", fake_urlopen)
    result = render_grounded(
        draft="Deterministic Ollama draft",
        facts={"status": "AVAILABLE", "member_count": 2},
        fact_refs=["analysis:C1"],
        purpose="ADVISOR",
    )

    assert captured["url"] == "https://ollama.com/api/chat"
    assert captured["timeout"] == 8.0
    assert captured["body"]["model"] == "gpt-oss:120b"
    assert captured["body"]["stream"] is False
    assert captured["body"]["options"] == {
        "temperature": 0,
        "num_predict": 1_200,
    }
    system_prompt = captured["body"]["messages"][0]["content"]
    assert "Preserve the primary language of the deterministic draft." in system_prompt
    assert (
        "If the draft is primarily Vietnamese, respond in Vietnamese." in system_prompt
    )
    assert "Do not translate unless explicitly requested." in system_prompt
    assert "Deterministic Ollama draft" in json.dumps(captured["body"])
    assert result.message == "Grounded Ollama text"
    assert "thinking" not in result.message.lower()
    assert "forbidden" not in result.message.lower()
    assert result.model == "gpt-oss:120b"
    assert result.provider_status == "OK"
    assert result.used_provider is True


@pytest.mark.parametrize(
    "payload",
    [
        {"message": {"content": "partial"}, "done": False},
        {"done": True},
        {"message": {}, "done": True},
        {"message": {"content": "   "}, "done": True},
    ],
)
def test_renderer_rejects_incomplete_ollama_responses(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, Any],
) -> None:
    _configure(monkeypatch)
    monkeypatch.setenv("AI_PROVIDER_PROTOCOL", "OLLAMA")
    monkeypatch.setattr(
        "nocpro_api.grounded_llm.urllib.request.urlopen",
        lambda *_args, **_kwargs: _Response(payload),
    )

    result = render_grounded(
        draft="Exact deterministic fallback",
        facts={"status": "AVAILABLE"},
        fact_refs=[],
        purpose="ASSISTANT",
    )

    assert result.message == "Exact deterministic fallback"
    assert result.provider_status == "INVALID_RESPONSE"
    assert result.used_provider is False


def test_renderer_rejects_unknown_protocol_without_network_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    monkeypatch.setenv("AI_PROVIDER_PROTOCOL", "AUTO_DETECT")
    monkeypatch.setattr(
        "nocpro_api.grounded_llm.urllib.request.urlopen",
        lambda *_args, **_kwargs: pytest.fail("invalid protocol must not call provider"),
    )

    result = render_grounded(
        draft="Protocol-safe deterministic fallback",
        facts={"status": "AVAILABLE"},
        fact_refs=[],
        purpose="ASSISTANT",
    )

    assert result.message == "Protocol-safe deterministic fallback"
    assert result.provider_status == "INVALID_CONFIGURATION"
    assert result.used_provider is False


def test_renderer_without_key_returns_exact_deterministic_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AI_API_KEY", raising=False)
    monkeypatch.setenv("AI_BASE_URL", "https://provider.invalid/v1")
    monkeypatch.setenv("AI_MODEL", "test-model")
    monkeypatch.setattr(
        "nocpro_api.grounded_llm.urllib.request.urlopen",
        lambda *_args, **_kwargs: pytest.fail("provider must not be called"),
    )

    result = render_grounded(
        draft="Keep this exact draft",
        facts={"status": "AVAILABLE"},
        fact_refs=[],
        purpose="ASSISTANT",
    )

    assert result.message == "Keep this exact draft"
    assert result.model == "DETERMINISTIC_EVIDENCE"
    assert result.provider_status == "NOT_CONFIGURED"
    assert result.used_provider is False


@pytest.mark.parametrize(
    ("provider_failure", "expected_status"),
    [
        (TimeoutError("slow provider"), "TIMEOUT"),
        (urllib.error.URLError("offline"), "PROVIDER_ERROR"),
        (
            urllib.error.HTTPError(
                "https://provider.invalid/v1/chat/completions",
                503,
                "contains-test-secret",
                None,
                None,
            ),
            "HTTP_ERROR",
        ),
    ],
)
def test_renderer_provider_failures_are_stable_and_do_not_expose_details(
    monkeypatch: pytest.MonkeyPatch,
    provider_failure: Exception,
    expected_status: str,
) -> None:
    _configure(monkeypatch)

    def fail(*_args: object, **_kwargs: object) -> _Response:
        raise provider_failure

    monkeypatch.setattr("nocpro_api.grounded_llm.urllib.request.urlopen", fail)
    result = render_grounded(
        draft="Safe deterministic fallback",
        facts={"status": "UNAVAILABLE"},
        fact_refs=["capability:MISSING"],
        purpose="ASSISTANT",
    )

    assert result.message == "Safe deterministic fallback"
    assert result.model == "DETERMINISTIC_EVIDENCE"
    assert result.provider_status == expected_status
    assert "test-secret" not in result.provider_status
    assert "contains-test-secret" not in result.provider_status


def test_unexpected_provider_error_does_not_log_secret_text(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _configure(monkeypatch)

    def fail(*_args: object, **_kwargs: object) -> _Response:
        raise RuntimeError("test-secret must not be logged")

    monkeypatch.setattr("nocpro_api.grounded_llm.urllib.request.urlopen", fail)
    with caplog.at_level(logging.ERROR):
        result = render_grounded(
            draft="Safe deterministic fallback",
            facts={},
            fact_refs=[],
            purpose="ADVISOR",
        )

    assert result.provider_status == "PROVIDER_ERROR"
    assert "test-secret" not in caplog.text


@pytest.mark.parametrize(
    "payload",
    [
        b"not-json",
        {},
        {"choices": []},
        {"choices": [{"message": {"content": "   "}}]},
        {"choices": [{"message": {"content": {"unexpected": "shape"}}}]},
    ],
)
def test_renderer_rejects_malformed_or_empty_responses(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, Any] | bytes,
) -> None:
    _configure(monkeypatch)
    monkeypatch.setattr(
        "nocpro_api.grounded_llm.urllib.request.urlopen",
        lambda *_args, **_kwargs: _Response(payload),
    )

    result = render_grounded(
        draft="Deterministic fallback",
        facts={"status": "AVAILABLE"},
        fact_refs=[],
        purpose="ADVISOR",
    )

    assert result.message == "Deterministic fallback"
    assert result.provider_status == "INVALID_RESPONSE"
    assert result.used_provider is False


def test_renderer_bounds_untrusted_input_and_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    captured: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: float) -> _Response:
        del timeout
        captured["body"] = request.data
        return _Response(
            {"choices": [{"message": {"content": "x" * 40_000}}]}
        )

    monkeypatch.setattr("nocpro_api.grounded_llm.urllib.request.urlopen", fake_urlopen)
    result = render_grounded(
        draft="d" * 40_000,
        facts={"untrusted_alarm_label": "a" * 40_000},
        fact_refs=["r" * 40_000],
        purpose="ASSISTANT",
    )

    assert len(captured["body"]) <= 32_000
    assert len(result.message) <= 12_000
    assert result.provider_status == "OK"
