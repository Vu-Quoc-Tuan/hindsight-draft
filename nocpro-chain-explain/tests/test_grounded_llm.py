"""Tests for the optional ADR-0024 grounded narrative provider."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
from pathlib import Path
from typing import Any

import pytest

from nocpro_api.grounded_llm import (
    GroundedAssistantCallResult,
    LLMToolCall,
    assistant_message_with_tool_calls,
    call_grounded_assistant,
    render_explain_trial_with_llm,
    render_grounded,
    tool_result_message,
    validate_grounded_content,
)
from nocpro_api.grounded_llm import (
    _MAX_OUTPUT_CHARS,
    _MAX_REQUEST_BYTES,
    _grounding_failure_reason,
    _grounding_is_preserved,
    _request_payload,
)
from nocpro_api.runtime_env import load_project_environment


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
    monkeypatch.setenv("AI_PROVIDER_PROTOCOL", "OPENAI_COMPATIBLE")


def test_project_environment_loads_dotenv_without_overriding_process_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "AI_API_KEY=file-secret\nAI_BASE_URL=https://provider.example/v1\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AI_API_KEY", "process-secret")
    monkeypatch.delenv("AI_BASE_URL", raising=False)

    loaded = load_project_environment(env_file)

    assert loaded is True
    assert os.environ["AI_API_KEY"] == "process-secret"
    assert os.environ["AI_BASE_URL"] == "https://provider.example/v1"


def test_returned_chart_narrative_rejects_unsupported_qualitative_claim() -> None:
    result = validate_grounded_content(
        content="Biểu đồ chứng minh tình trạng đang xấu đi nghiêm trọng.",
        draft="Số liệu biểu đồ lấy từ persisted Audit artifact.",
        facts={"status": "AVAILABLE"},
        fact_refs=["audit-job:J1"],
        model="test-model",
        provider_status="OK",
    )

    assert result.message == ""
    assert result.provider_status == "GROUNDING_UNSUPPORTED_CLAIM"
    assert result.used_provider is False


def test_grounding_accepts_explicitly_uncertain_causal_language() -> None:
    draft = "Quan hệ nhân quả chưa được xác định."
    facts = {"device": "ROUTER-01"}

    assert _grounding_is_preserved(
        "Dữ liệu chưa chứng minh ROUTER-01 gây ra sự cố.",
        draft,
        facts,
        [],
    )
    assert not _grounding_is_preserved(
        "Dữ liệu chứng minh ROUTER-01 gây ra sự cố.",
        draft,
        facts,
        [],
    )


def test_grounding_accepts_observed_order_disclaimer_before_transmission_claim() -> None:
    draft = "Đây là thứ tự quan sát, chưa phải bằng chứng về hướng lan truyền."

    assert _grounding_is_preserved(
        draft,
        draft,
        {},
        [],
    )


def test_grounding_does_not_treat_hyphenated_prose_as_an_identifier() -> None:
    assert _grounding_is_preserved(
        "Cần kiểm tra quan hệ cross-layer và end-to-end.",
        "Cần kiểm tra quan hệ giữa các lớp.",
        {},
        [],
    )
    assert not _grounding_is_preserved(
        "Cần kiểm tra INVENTED_ROUTER.",
        "Cần kiểm tra ROUTER_01.",
        {"device": "ROUTER_01"},
        [],
    )


def test_returned_chart_narrative_accepts_exact_projection_modulo_whitespace() -> None:
    result = validate_grounded_content(
        content="Số liệu  biểu đồ\n lấy từ persisted Audit artifact.",
        draft="Số liệu biểu đồ lấy từ persisted Audit artifact.",
        facts={"status": "AVAILABLE"},
        fact_refs=["audit-job:J1"],
        model="test-model",
        provider_status="OK",
    )

    assert result.message == "Số liệu  biểu đồ\n lấy từ persisted Audit artifact."
    assert result.provider_status == "OK"
    assert result.used_provider is True


def test_grounding_keeps_percentage_units_distinct_from_counts() -> None:
    assert _grounding_is_preserved("Coverage is 5%.", "Coverage is 5%.", {}, [])
    assert not _grounding_is_preserved("Coverage is 5%.", "Coverage is 5.", {}, [])
    assert not _grounding_is_preserved("Coverage is 5%.", "Alarm count is 5.", {}, [])


def test_grounding_checks_complete_ipv4_addresses() -> None:
    draft = "Quan sát 10.208.94.101 và 10.209.108.94."
    facts = {"devices": ["10.208.94.101", "10.209.108.94"]}

    assert _grounding_failure_reason("Kiểm tra 10.208.94.101.", draft, facts, []) is None
    assert _grounding_failure_reason(
        "Kiểm tra 10.208.108.94.", draft, facts, []
    ) == "IP_MISMATCH"
    assert _grounding_failure_reason(
        "Kiểm tra 10.208.94.999.", draft, facts, []
    ) == "IP_MISMATCH"


def test_cohesion_prompt_prefers_focus_without_a_sentence_or_word_cap() -> None:
    body = json.loads(_request_payload(
        draft="Quan sát hai thiết bị.",
        facts={"investigation_evidence": {"status": "AVAILABLE"}},
        fact_refs=[],
        purpose="COHESION",
        model="test-model",
        protocol="OLLAMA",
    ))
    system_prompt = body["messages"][0]["content"]

    assert "Prefer a focused paragraph" in system_prompt
    assert "use as much detail as a complex relationship needs" in system_prompt
    assert "3-4 sentence" not in system_prompt
    assert "max words" not in system_prompt


def test_grounding_does_not_treat_editorial_instruction_as_numeric_evidence() -> None:
    draft = "Có cảnh báo cần kiểm tra."
    assert _grounding_failure_reason(
        "Có 5 cảnh báo.", draft, {"instruction": "Viết 5 câu."}, []
    ) == "NUMBER_MISMATCH"
    assert _grounding_failure_reason(
        "Có 5 cảnh báo.",
        draft,
        {"instruction": "Viết gọn.", "investigation_evidence": {"alarm_count": 5}},
        [],
    ) is None


def test_grounding_allows_generic_tier_name_without_authorizing_its_digit() -> None:
    draft = "Đánh giá cấu trúc cần đối chiếu thêm."
    facts = {"instruction": "Đối chiếu Tier-2 khi có dữ liệu."}

    assert _grounding_failure_reason(
        "Tier-2 cần được đối chiếu thêm.", draft, facts, []
    ) is None
    assert _grounding_failure_reason(
        "Tier-2 ghi nhận 2 cảnh báo.", draft, facts, []
    ) == "NUMBER_MISMATCH"


def test_ip_and_identifier_digits_do_not_authorize_unrelated_counts() -> None:
    draft = "Quan sát ROUTER-05 tại 10.208.94.101."
    facts = {"device": "ROUTER-05", "ip": "10.208.94.101"}

    assert _grounding_failure_reason("Có 5 cảnh báo.", draft, facts, []) == "NUMBER_MISMATCH"
    assert _grounding_failure_reason("Có 10 cảnh báo.", draft, facts, []) == "NUMBER_MISMATCH"


def test_unverified_topology_cannot_be_called_a_verified_directed_dependency() -> None:
    draft = "ROUTER-01 và ROUTER-02 có đường topology cấu trúc."
    facts = {
        "investigation_evidence": {
            "topology": {
                "paths": [{"source": "ROUTER-01", "target": "ROUTER-02"}],
                "dependency_verified": False,
            }
        }
    }

    assert _grounding_failure_reason(
        "Topology xác nhận quan hệ phụ thuộc có hướng giữa ROUTER-01 và ROUTER-02.",
        draft,
        facts,
        [],
    ) == "UNSUPPORTED_RELATION"
    assert _grounding_failure_reason(
        "Topology chưa xác nhận quan hệ phụ thuộc có hướng giữa ROUTER-01 và ROUTER-02.",
        draft,
        facts,
        [],
    ) is None


def test_rejected_trial_response_discards_untrusted_llm_score(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)
    monkeypatch.setattr(
        "nocpro_api.grounded_llm.urllib.request.urlopen",
        lambda *_args, **_kwargs: _Response(
            {"choices": [{"message": {"content": '{"explanation":"999 alarms","llm_score":100}'}}]}
        ),
    )

    result = render_explain_trial_with_llm(
        draft="3 alarms",
        facts={"alarm_count": 3},
        fact_refs=["chain:C1"],
    )

    assert result.message == ""
    assert result.llm_score is None
    assert result.provider_status == "GROUNDING_NUMBER_MISMATCH"
    assert result.used_provider is False


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


def test_cohesion_debug_mode_keeps_provider_prose_and_requests_vietnamese(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    captured: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: float) -> _Response:
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _Response(
            {
                "choices": [
                    {
                        "message": {
                            "content": "Root cause proven: Router-Z caused the incident."
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr("nocpro_api.grounded_llm.urllib.request.urlopen", fake_urlopen)
    result = render_grounded(
        draft="Thứ tự quan sát chưa chứng minh hướng lan truyền.",
        facts={"investigation_evidence": {"topology": {"dependency_verified": False}}},
        fact_refs=["analysis:C1"],
        purpose="COHESION",
        requested_language="vi",
        preserve_provider_output=True,
    )

    assert result.message == "Root cause proven: Router-Z caused the incident."
    assert result.model == "test-model"
    assert result.provider_status == "GROUNDING_FORBIDDEN_CLAIM"
    assert result.used_provider is True
    system_prompt = captured["body"]["messages"][0]["content"]
    assert "OUTPUT LANGUAGE = Vietnamese" in system_prompt
    assert "Do not answer in English" in system_prompt


def test_renderer_rejects_provider_narrative_that_claims_causality_or_apply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    monkeypatch.setattr(
        "nocpro_api.grounded_llm.urllib.request.urlopen",
        lambda *_args, **_kwargs: _Response(
            {
                "choices": [
                    {
                        "message": {
                            "content": "Root cause proven: Router-Z caused the incident. Apply MERGE now."
                        }
                    }
                ]
            }
        ),
    )

    result = render_grounded(
        draft="Root cause is unavailable. Proposal only.",
        facts={"root_cause": "UNAVAILABLE"},
        fact_refs=["analysis:C1"],
        purpose="ASSISTANT",
    )

    assert result.message == ""
    assert result.provider_status == "GROUNDING_VIOLATION"
    assert result.used_provider is False


def test_renderer_rejects_vietnamese_causal_shortcuts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    monkeypatch.setattr(
        "nocpro_api.grounded_llm.urllib.request.urlopen",
        lambda *_args, **_kwargs: _Response(
            {
                "choices": [
                    {
                        "message": {
                            "content": "Sự cố mạng tạo ra đợt lỗi rồi lan rộng sang thiết bị khác."
                        }
                    }
                ]
            }
        ),
    )

    result = render_grounded(
        draft="Thứ tự quan sát chưa chứng minh hướng lan truyền.",
        facts={"status": "AVAILABLE"},
        fact_refs=["analysis:C1"],
        purpose="COHESION",
    )

    assert result.provider_status == "GROUNDING_FORBIDDEN_CLAIM"
    assert result.message == ""
    assert result.used_provider is False


def test_cohesion_dev_probe_returns_raw_provider_prose_without_persistable_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    monkeypatch.setenv("AI_PROVIDER_PROTOCOL", "OLLAMA")
    monkeypatch.setenv("NOCPRO_BYPASS_COHESION_GROUNDING", "true")
    raw_message = "Sự cố mạng tạo ra đợt lỗi rồi lan rộng sang thiết bị khác."
    monkeypatch.setattr(
        "nocpro_api.grounded_llm.urllib.request.urlopen",
        lambda *_args, **_kwargs: _Response(
            {
                "model": "test-model",
                "message": {"role": "assistant", "content": raw_message},
                "done": True,
            }
        ),
    )

    result = render_grounded(
        draft="Thứ tự quan sát chưa chứng minh hướng lan truyền.",
        facts={"status": "AVAILABLE"},
        fact_refs=["analysis:C1"],
        purpose="COHESION",
    )

    assert result.message == raw_message
    assert result.provider_status == "GROUNDING_BYPASS"
    assert result.model == "test-model"
    assert result.used_provider is True


def test_cohesion_dev_probe_is_refused_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)
    monkeypatch.setenv("AI_PROVIDER_PROTOCOL", "OLLAMA")
    monkeypatch.setenv("NOCPRO_BYPASS_COHESION_GROUNDING", "true")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setattr(
        "nocpro_api.grounded_llm.urllib.request.urlopen",
        lambda *_args, **_kwargs: _Response(
            {
                "model": "test-model",
                "message": {
                    "role": "assistant",
                    "content": "Sự cố mạng tạo ra đợt lỗi rồi lan rộng sang thiết bị khác.",
                },
                "done": True,
            }
        ),
    )

    result = render_grounded(
        draft="Thứ tự quan sát chưa chứng minh hướng lan truyền.",
        facts={"status": "AVAILABLE"},
        fact_refs=["analysis:C1"],
        purpose="COHESION",
    )

    assert result.provider_status == "GROUNDING_FORBIDDEN_CLAIM"
    assert result.used_provider is False


def test_dev_grounding_bypass_can_inspect_raw_advisor_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    monkeypatch.setenv("NOCPRO_BYPASS_GROUNDING", "true")
    raw_message = "Root cause proven: Router-Z caused the incident."
    monkeypatch.setattr(
        "nocpro_api.grounded_llm.urllib.request.urlopen",
        lambda *_args, **_kwargs: _Response(
            {"choices": [{"message": {"content": raw_message}}]}
        ),
    )

    result = render_grounded(
        draft="Quan sát chưa chứng minh hướng lan truyền.",
        facts={"status": "AVAILABLE"},
        fact_refs=["analysis:C1"],
        purpose="ADVISOR",
        requested_language="vi",
        preserve_provider_output=True,
    )

    assert result.message == raw_message
    assert result.provider_status == "GROUNDING_BYPASS"
    assert result.used_provider is True


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
    assert captured["body"]["think"] is False
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


def test_ollama_request_keeps_an_ordered_fact_ref_prefix_within_total_byte_budget() -> None:
    refs = [f"ref-{index:02d}-" + ("x" * 250) for index in range(64)]

    encoded = _request_payload(
        draft="D" * 6_000,
        facts={"evidence": "F" * 8_000},
        fact_refs=refs,
        purpose="COHESION",
        model="gpt-oss:120b",
        protocol="OLLAMA",
    )

    assert len(encoded) <= _MAX_REQUEST_BYTES
    payload = json.loads(encoded.decode("utf-8"))
    assert payload["options"] == {"temperature": 0}
    assert "Synthesize the investigation insight" in payload["messages"][1]["content"]
    assert "Render the deterministic draft" not in payload["messages"][1]["content"]
    user_content = payload["messages"][1]["content"]
    grounding_json = user_content.split("<GROUNDING_DATA>\n", 1)[1].split(
        "\n</GROUNDING_DATA>", 1
    )[0]
    retained_refs = json.loads(grounding_json)["fact_refs"]
    assert 0 < len(retained_refs) < len(refs)
    for retained, original in zip(retained_refs, refs[: len(retained_refs)], strict=True):
        assert retained.startswith(original[:200])


def test_renderer_retries_one_incomplete_ollama_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    monkeypatch.setenv("AI_PROVIDER_PROTOCOL", "OLLAMA")
    responses = iter(
        [
            _Response({"message": {"content": ""}, "done": True}),
            _Response({"message": {"content": "Grounded retry text."}, "done": True}),
        ]
    )
    call_count = 0

    def fake_urlopen(*_args: object, **_kwargs: object) -> _Response:
        nonlocal call_count
        call_count += 1
        return next(responses)

    monkeypatch.setattr("nocpro_api.grounded_llm.urllib.request.urlopen", fake_urlopen)
    result = render_grounded(
        draft="Grounded retry text.",
        facts={"status": "AVAILABLE"},
        fact_refs=[],
        purpose="COHESION",
    )

    assert call_count == 2
    assert result.provider_status == "OK"
    assert result.message == "Grounded retry text."


@pytest.mark.parametrize(
    "payload",
    [
        {"message": {"content": "Câu trả lời đã bị cắt."}, "done": True, "done_reason": "length"},
        {"message": {"content": "Câu trả lời đang dừng giữa chừng"}, "done": True, "done_reason": "stop"},
    ],
)
def test_cohesion_renderer_rejects_cut_off_ollama_prose_after_one_retry(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, Any],
) -> None:
    _configure(monkeypatch)
    monkeypatch.setenv("AI_PROVIDER_PROTOCOL", "OLLAMA")
    call_count = 0

    def fake_urlopen(*_args: object, **_kwargs: object) -> _Response:
        nonlocal call_count
        call_count += 1
        return _Response(payload)

    monkeypatch.setattr("nocpro_api.grounded_llm.urllib.request.urlopen", fake_urlopen)
    result = render_grounded(
        draft="Fallback hoàn chỉnh.",
        facts={"status": "AVAILABLE"},
        fact_refs=[],
        purpose="COHESION",
    )

    assert call_count == 2
    assert result.provider_status == "INCOMPLETE_RESPONSE"
    assert result.message == ""


def test_cohesion_renderer_retries_one_grounding_violation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    monkeypatch.setenv("AI_PROVIDER_PROTOCOL", "OLLAMA")
    responses = iter(
        [
            _Response(
                {
                    "message": {"content": "Thiết bị INVENTED-ROUTER cần được kiểm tra."},
                    "done": True,
                    "done_reason": "stop",
                }
            ),
            _Response(
                {
                    "message": {"content": "Thiết bị ROUTER-01 cần được kiểm tra."},
                    "done": True,
                    "done_reason": "stop",
                }
            ),
        ]
    )
    call_count = 0

    def fake_urlopen(*_args: object, **_kwargs: object) -> _Response:
        nonlocal call_count
        call_count += 1
        return next(responses)

    monkeypatch.setattr("nocpro_api.grounded_llm.urllib.request.urlopen", fake_urlopen)
    result = render_grounded(
        draft="Cần kiểm tra thiết bị ROUTER-01.",
        facts={"device": "ROUTER-01"},
        fact_refs=[],
        purpose="COHESION",
    )

    assert call_count == 2
    assert result.provider_status == "OK"
    assert result.message == "Thiết bị ROUTER-01 cần được kiểm tra."


def test_cohesion_renderer_never_returns_server_truncated_prose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    monkeypatch.setenv("AI_PROVIDER_PROTOCOL", "OLLAMA")
    oversized = "Một nhận định có nhiều chi tiết. " * (_MAX_OUTPUT_CHARS // 20)
    call_count = 0

    def fake_urlopen(*_args: object, **_kwargs: object) -> _Response:
        nonlocal call_count
        call_count += 1
        return _Response({"message": {"content": oversized}, "done": True})

    monkeypatch.setattr("nocpro_api.grounded_llm.urllib.request.urlopen", fake_urlopen)
    result = render_grounded(
        draft="Nhận định dự phòng hoàn chỉnh.",
        facts={"investigation_evidence": {"status": "AVAILABLE"}},
        fact_refs=[],
        purpose="COHESION",
    )

    assert call_count == 2
    assert result.provider_status == "OUTPUT_TOO_LONG"
    assert result.message == ""
    assert "[TRUNCATED_BY_SERVER]" not in result.message


def test_cohesion_renderer_surfaces_complete_ip_mismatch_after_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    monkeypatch.setenv("AI_PROVIDER_PROTOCOL", "OLLAMA")
    call_count = 0

    def fake_urlopen(*_args: object, **_kwargs: object) -> _Response:
        nonlocal call_count
        call_count += 1
        return _Response({
            "message": {"content": "Kiểm tra 10.208.108.94."},
            "done": True,
        })

    monkeypatch.setattr("nocpro_api.grounded_llm.urllib.request.urlopen", fake_urlopen)
    result = render_grounded(
        draft="Quan sát 10.208.94.101 và 10.209.108.94.",
        facts={"devices": ["10.208.94.101", "10.209.108.94"]},
        fact_refs=[],
        purpose="COHESION",
    )

    assert call_count == 2
    assert result.provider_status == "GROUNDING_IP_MISMATCH"
    assert result.used_provider is False


def test_renderer_retries_incomplete_ollama_response_only_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    monkeypatch.setenv("AI_PROVIDER_PROTOCOL", "OLLAMA")
    call_count = 0

    def fake_urlopen(*_args: object, **_kwargs: object) -> _Response:
        nonlocal call_count
        call_count += 1
        return _Response({"message": {"content": ""}, "done": True})

    monkeypatch.setattr("nocpro_api.grounded_llm.urllib.request.urlopen", fake_urlopen)
    result = render_grounded(
        draft="Safe fallback",
        facts={"status": "AVAILABLE"},
        fact_refs=[],
        purpose="COHESION",
    )

    assert call_count == 2
    assert result.provider_status == "INVALID_RESPONSE"
    assert result.message == ""


def test_renderer_classifies_mandatory_payload_overflow_as_request_too_large(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    monkeypatch.setenv("AI_PROVIDER_PROTOCOL", "OLLAMA")
    monkeypatch.setenv("AI_MODEL", "model-" + ("x" * _MAX_REQUEST_BYTES))
    monkeypatch.setattr(
        "nocpro_api.grounded_llm.urllib.request.urlopen",
        lambda *_args, **_kwargs: pytest.fail("oversized local request must not be sent"),
    )

    result = render_grounded(
        draft="Safe fallback",
        facts={"status": "AVAILABLE"},
        fact_refs=[],
        purpose="COHESION",
    )

    assert result.provider_status == "REQUEST_TOO_LARGE"
    assert result.message == ""


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

    assert result.message == ""
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

    assert result.message == ""
    assert result.provider_status == "INVALID_CONFIGURATION"
    assert result.used_provider is False


def test_renderer_without_key_returns_empty_provider_output(
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

    assert result.message == ""
    assert result.model == "test-model"
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
            "HTTP_UPSTREAM_ERROR",
        ),
        (
            urllib.error.HTTPError(
                "https://provider.invalid/v1/chat/completions",
                401,
                "unauthorized",
                None,
                None,
            ),
            "HTTP_AUTH_ERROR",
        ),
        (
            urllib.error.HTTPError(
                "https://provider.invalid/v1/chat/completions",
                429,
                "rate-limited",
                None,
                None,
            ),
            "HTTP_RATE_LIMITED",
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

    assert result.message == ""
    assert result.model == "test-model"
    assert result.provider_status == expected_status
    assert "test-secret" not in result.provider_status
    assert "contains-test-secret" not in result.provider_status


def test_production_raw_mode_does_not_replace_provider_failure_with_deterministic_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)

    def fail(*_args: object, **_kwargs: object) -> _Response:
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("nocpro_api.grounded_llm.urllib.request.urlopen", fail)
    result = render_grounded(
        draft="Không được hiển thị như một câu trả lời của AI.",
        facts={"status": "AVAILABLE"},
        fact_refs=["analysis:C1"],
        purpose="COHESION",
        requested_language="vi",
        preserve_provider_output=True,
    )

    assert result.message == ""
    assert result.model == "test-model"
    assert result.provider_status == "PROVIDER_ERROR"
    assert result.used_provider is False


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

    assert result.message == ""
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


def test_openai_tool_round_uses_string_arguments_and_tool_call_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    captured: dict[str, Any] = {}

    def fake_urlopen(request: Any, **_kwargs: Any) -> _Response:
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _Response({"choices": [{"message": {"content": "final"}}]})

    monkeypatch.setattr("nocpro_api.grounded_llm.urllib.request.urlopen", fake_urlopen)
    selected = GroundedAssistantCallResult(
        content=None,
        tool_calls=[LLMToolCall("search_project_knowledge", {"query": "phi"}, "call-1")],
        model="test-model",
        provider_status="OK",
        used_provider=True,
    )
    messages = [
        {"role": "user", "content": "phi?"},
        assistant_message_with_tool_calls(selected),
        tool_result_message("call-1", "search_project_knowledge", {"status": "AVAILABLE"}, "OPENAI_COMPATIBLE"),
    ]
    result = call_grounded_assistant(messages, tools=[])

    assert result.content == "final"
    assert isinstance(captured["body"]["messages"][1]["tool_calls"][0]["function"]["arguments"], str)
    assert captured["body"]["messages"][2]["tool_call_id"] == "call-1"
    assert "tool_name" not in captured["body"]["messages"][2]


def test_ollama_tool_round_uses_object_arguments_and_tool_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    monkeypatch.setenv("AI_PROVIDER_PROTOCOL", "OLLAMA")
    captured: dict[str, Any] = {}

    def fake_urlopen(request: Any, **_kwargs: Any) -> _Response:
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _Response({"message": {"content": "final"}, "done": True})

    monkeypatch.setattr("nocpro_api.grounded_llm.urllib.request.urlopen", fake_urlopen)
    selected = GroundedAssistantCallResult(
        content=None,
        tool_calls=[LLMToolCall("search_project_knowledge", {"query": "phi"})],
        model="test-model",
        provider_status="OK",
        used_provider=True,
    )
    messages = [
        {"role": "user", "content": "phi?"},
        assistant_message_with_tool_calls(selected),
        tool_result_message("call-0", "search_project_knowledge", {"status": "AVAILABLE"}, "OLLAMA"),
    ]
    result = call_grounded_assistant(messages, tools=[])

    assert result.content == "final"
    assert captured["body"]["messages"][1]["tool_calls"][0]["function"]["arguments"] == {"query": "phi"}
    assert captured["body"]["messages"][2]["tool_name"] == "search_project_knowledge"
    assert "tool_call_id" not in captured["body"]["messages"][2]
