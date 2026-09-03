"""AI Operational Advisor for NocPro Chain Explanations.

Adheres strictly to ADR-0024:
- LLMs are used ONLY for grounded narrative rendering and synthesis.
- LLMs NEVER invent evidence, change scores, infer ungrounded causes, or alter chains.
- Fail-closed / Fail-safe: If LLM is unreachable or disabled, the core engine
  produces deterministic grounded narratives without failing.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
ENV_PATH = ROOT / ".env"


def _ensure_env_loaded() -> None:
    if not ENV_PATH.is_file():
        return
    try:
        content = ENV_PATH.read_text(encoding="utf-8")
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip().strip("'\"")
            if k and k not in os.environ:
                os.environ[k] = v
    except Exception as exc:
        logger.debug("Failed to read .env: %s", exc)


_ensure_env_loaded()


@dataclass(frozen=True)
class AISuggestionResult:
    chain_id: str
    status: str
    model: str
    narrative: str
    grounded_claims: list[str]
    disclaimer: str
    provider_status: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def extract_grounded_claims(
    chain_id: str,
    analysis: Any,
    review_result: dict[str, Any] | None = None,
    topology_result: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Extract strictly deterministic structured facts and claims (ADR-0024)."""
    members_raw = getattr(analysis, "members", [])
    if isinstance(members_raw, dict):
        members = []
        for aid, m in members_raw.items():
            role_val = getattr(getattr(m, "role", None), "verdict", None)
            if hasattr(role_val, "value"):
                role_val = role_val.value
            fit_val = getattr(getattr(m, "fit", None), "value", None) or getattr(m, "fit", None)
            if hasattr(fit_val, "value"):
                fit_val = fit_val.value
            members.append({
                "alarm_id": aid,
                "device_code": getattr(m, "device_code", ""),
                "role": str(role_val or "UNKNOWN"),
                "fit": str(fit_val or "NORMAL"),
            })
    elif isinstance(members_raw, (list, tuple)):
        members = list(members_raw)
    else:
        members = []

    rc = getattr(analysis, "role_counts", {})
    if callable(rc):
        role_counts = rc()
    elif isinstance(rc, dict):
        role_counts = rc
    else:
        role_counts = {}

    claims_list: list[str] = []
    member_count = len(members)
    claims_list.append(f"Chuỗi {chain_id} bao gồm {member_count} cảnh báo.")

    # Roles and weak members
    weak_members: list[str] = []
    root_members: list[str] = []
    for m in members:
        role = getattr(m, "role", None) or (m.get("role") if isinstance(m, dict) else None)
        fit = getattr(m, "fit", None) or (m.get("fit") if isinstance(m, dict) else None)
        aid = getattr(m, "alarm_id", None) or (m.get("alarm_id") if isinstance(m, dict) else "unknown")
        dev = getattr(m, "device_code", None) or (m.get("device_code") if isinstance(m, dict) else "")

        if fit == "WEAK":
            weak_members.append(f"{aid} ({dev})" if dev else aid)
        if role in {"ROOT", "PRIMARY"}:
            root_members.append(f"{aid} ({dev})" if dev else aid)

    if weak_members:
        claims_list.append(f"Phát hiện {len(weak_members)} cảnh báo có độ tương quan yếu: {', '.join(weak_members[:3])}")
    else:
        claims_list.append("Tất cả cảnh báo trong chuỗi đều có độ gắn kết (fit) cao.")

    # Descriptors
    raw_desc = getattr(analysis, "descriptors", [])
    if hasattr(raw_desc, "identity") and hasattr(raw_desc, "contrastive"):
        desc_list = list(raw_desc.identity) + list(raw_desc.contrastive)
    elif isinstance(raw_desc, (list, tuple)):
        desc_list = list(raw_desc)
    else:
        desc_list = []

    top_desc: list[str] = []
    for d in desc_list[:3]:
        label = getattr(d, "label", None) or (d.get("label") if isinstance(d, dict) else "")
        cov = getattr(d, "coverage", None) or (d.get("coverage") if isinstance(d, dict) else 0)
        top_desc.append(f"{label} (phủ {cov:.0%})")
    if top_desc:
        claims_list.append(f"Mô tả quy luật đặc trưng: {', '.join(top_desc)}")

    # Counterfactual proposals
    proposals: list[dict[str, Any]] = []
    if review_result:
        recommendations = review_result.get("recommendations", [])
        evaluated = review_result.get("evaluated_candidates", [])
        for rec in (recommendations or evaluated[:2]):
            cid = rec.get("candidate_id") if isinstance(rec, dict) else getattr(rec, "candidate_id", "")
            op = rec.get("operation") if isinstance(rec, dict) else getattr(rec, "operation", "")
            if cid and op:
                proposals.append({"candidate_id": cid, "operation": op})
                claims_list.append(f"Đề xuất phản nghiệm khả thi: {op} (Mã đề xuất: {cid})")

    # Topology
    topo_summary: dict[str, Any] = {}
    if topology_result:
        dominator = topology_result.get("dominator", {})
        propagation = topology_result.get("propagation", {})
        if dominator.get("status") == "AVAILABLE":
            root_candidate = dominator.get("root_candidate")
            if root_candidate:
                topo_summary["dominator_root"] = root_candidate
                claims_list.append(f"Topology Dominator xác định thiết bị chi phối: {root_candidate}")
        if propagation.get("status") == "AVAILABLE":
            topo_summary["propagation_status"] = "AVAILABLE"

    structured_data = {
        "chain_id": chain_id,
        "member_count": member_count,
        "role_counts": role_counts,
        "weak_members": weak_members,
        "root_members": root_members,
        "descriptors": top_desc,
        "proposals": proposals,
        "topology": topo_summary,
    }
    return structured_data, claims_list


def build_deterministic_narrative(
    chain_id: str,
    structured_data: dict[str, Any],
    claims_list: list[str],
) -> str:
    """Construct an objective deterministic narrative without requiring an LLM."""
    member_count = structured_data["member_count"]
    weak_members = structured_data["weak_members"]
    root_members = structured_data["root_members"]
    descriptors = structured_data["descriptors"]
    proposals = structured_data["proposals"]
    topology = structured_data.get("topology", {})

    lines: list[str] = [
        f"### 📋 Tóm tắt chuỗi sự cố {chain_id}",
        f"- Quy mô chuỗi: **{member_count} cảnh báo** phát sinh đồng thời trên hạ tầng mạng Viettel.",
    ]

    if root_members:
        lines.append(f"- Cảnh báo hạt nhân / khởi phát được phát hiện: **{', '.join(root_members[:3])}**.")
    if descriptors:
        lines.append(f"- Đặc trưng nhận dạng nổi bật: {', '.join(descriptors)}.")

    lines.append("\n### 🎯 Phân tích thiết bị trọng yếu & Gắn kết chuỗi")
    if weak_members:
        lines.append(
            f"- Hệ thống phát hiện **{len(weak_members)} cảnh báo có độ tương quan yếu** ({', '.join(weak_members[:3])}). "
            "Các cảnh báo này có khả năng bị gom nhầm do trùng cửa sổ thời gian nhưng khác vùng lỗi vật lý."
        )
    else:
        lines.append("- Các phần tử trong chuỗi có mối liên hệ nhân quả và cấu trúc topo đồng nhất, độ gắn kết chặt chẽ.")

    if topology.get("dominator_root"):
        lines.append(f"- Căn cứ tiểu đồ thị topo IP, thiết bị **{topology['dominator_root']}** đóng vai trò điểm nút lan truyền lỗi chính.")

    lines.append("\n### 💡 Khuyến nghị vận hành & Phân hoạch (Human-in-the-Loop)")
    if proposals:
        for p in proposals:
            lines.append(
                f"- Đề xuất **{p['operation']}** (Mã: `{p['candidate_id']}`): "
                "Cải thiện hệ số phân tách mạng. Kỹ sư vận hành nên xem xét bấm **[ Chấp thuận đề xuất ]** trên giao diện Review."
            )
    elif weak_members:
        lines.append("- Khuyến nghị chạy Counterfactual Review để xem xét tách (SPLIT) hoặc loại bỏ (REMOVE) các cảnh báo yếu.")
    else:
        lines.append("- Duy trì phân hoạch hiện tại của NocPro, tập trung xử lý nguyên nhân tại thiết bị khởi phát.")

    lines.append(
        "\n> [!NOTE]\n"
        "> Bản diễn giải được tổng hợp trực tiếp từ kết quả phân tích toán học xác định (Deterministic Evidence - ADR-0024). "
        "Mọi quyết định chia/gộp chuỗi cần có sự phê duyệt của kỹ sư NOC."
    )
    return "\n".join(lines)


def generate_ai_suggestion(
    chain_id: str,
    analysis: Any,
    review_result: dict[str, Any] | None = None,
    topology_result: dict[str, Any] | None = None,
    timeout: float = 8.0,
) -> AISuggestionResult:
    """Generate an operational narrative adhering to ADR-0024.

    Tries the configured LLM endpoint (Mistral-Large) first.
    If unavailable or encountering provider restrictions, safely returns
    a high-fidelity deterministic grounded narrative.
    """
    _ensure_env_loaded()
    structured_data, claims_list = extract_grounded_claims(
        chain_id, analysis, review_result, topology_result
    )
    fallback_narrative = build_deterministic_narrative(
        chain_id, structured_data, claims_list
    )

    base_url = os.environ.get("AI_BASE_URL", "https://router.bynara.id/v1").rstrip("/")
    api_key = os.environ.get("AI_API_KEY", "")
    model = os.environ.get("AI_MODEL", "mistral-large")
    disclaimer = (
        "Bản diễn giải do AI hỗ trợ dựa hoàn toàn trên bằng chứng xác định (ADR-0024). "
        "AI không tự tạo evidence, không tự sửa điểm số, không tự ý thay đổi hệ thống."
    )

    if not api_key:
        return AISuggestionResult(
            chain_id=chain_id,
            status="FALLBACK",
            model="deterministic-synthesizer",
            narrative=fallback_narrative,
            grounded_claims=claims_list,
            disclaimer=disclaimer,
            provider_status="NO_API_KEY_CONFIGURED",
        )

    # Prepare LLM Request adhering to ADR-0024
    system_prompt = (
        "Bạn là Trợ lý Cố vấn Vận hành AI thuộc hệ thống Viettel NocPro (NocPro Chain Explain).\n"
        "NGUYÊN TẮC BẮT BUỘC (ADR-0024):\n"
        "1. Bạn CHỈ ĐƯỢC PHÉP diễn giải và tổng hợp dựa trên dữ liệu bằng chứng xác định (Deterministic Evidence) được cung cấp trong câu hỏi.\n"
        "2. TUYỆT ĐỐI KHÔNG tự bịa đặt thiết bị, cảnh báo, liên kết topo hoặc chỉ số không có trong dữ liệu.\n"
        "3. TUYỆT ĐỐI KHÔNG tự ý sửa đổi điểm số, không tự quyết định thay đổi hệ thống.\n"
        "4. Trả lời bằng tiếng Việt chuyên nghiệp, súc tích, định dạng Markdown rõ ràng theo 4 phần:\n"
        "   - 📋 Tóm tắt trạng thái chuỗi sự cố\n"
        "   - 🎯 Phân tích thiết bị trọng yếu & Nguyên nhân nghi vấn\n"
        "   - 💡 Khuyến nghị vận hành & Đề xuất phân hoạch\n"
        "   - ⚠️ Lưu ý an toàn cho Kỹ sư NOC"
    )

    user_prompt = (
        f"Dữ liệu phân tích xác định của chuỗi cảnh báo {chain_id}:\n"
        f"{json.dumps(structured_data, ensure_ascii=False, indent=2)}\n\n"
        f"Các mệnh đề bằng chứng đã kiểm chứng:\n"
        + "\n".join(f"- {c}" for c in claims_list)
        + "\n\nHãy tổng hợp bản cố vấn vận hành súc tích cho kỹ sư NOC theo đúng nguyên tắc ADR-0024."
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 1200,
    }

    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=req_data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "nocpro-chain-explain/ai-advisor",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            resp_data = json.loads(response.read().decode("utf-8"))
            choices = resp_data.get("choices", [])
            if choices and choices[0].get("message", {}).get("content"):
                llm_content = choices[0]["message"]["content"].strip()
                return AISuggestionResult(
                    chain_id=chain_id,
                    status="AVAILABLE",
                    model=model,
                    narrative=llm_content,
                    grounded_claims=claims_list,
                    disclaimer=disclaimer,
                    provider_status="OK",
                )
    except urllib.error.HTTPError as exc:
        err_msg = ""
        try:
            err_data = json.loads(exc.read().decode("utf-8"))
            err_msg = err_data.get("error", {}).get("message") or str(err_data)
        except Exception:
            err_msg = f"HTTP {exc.code}: {exc.reason}"
        logger.info("AI LLM endpoint returned %s; using deterministic fallback", err_msg)
        return AISuggestionResult(
            chain_id=chain_id,
            status="FALLBACK",
            model=f"{model} (fallback)",
            narrative=fallback_narrative,
            grounded_claims=claims_list,
            disclaimer=disclaimer,
            provider_status=err_msg,
        )
    except Exception as exc:
        logger.info("AI LLM call failed (%s); using deterministic fallback", exc)
        return AISuggestionResult(
            chain_id=chain_id,
            status="FALLBACK",
            model=f"{model} (fallback)",
            narrative=fallback_narrative,
            grounded_claims=claims_list,
            disclaimer=disclaimer,
            provider_status=str(exc),
        )

    return AISuggestionResult(
        chain_id=chain_id,
        status="FALLBACK",
        model=model,
        narrative=fallback_narrative,
        grounded_claims=claims_list,
        disclaimer=disclaimer,
        provider_status="EMPTY_LLM_RESPONSE",
    )
