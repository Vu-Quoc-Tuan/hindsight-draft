"""Cohesion narrative generator grounded on 5 authoritative data sources (ADR-0024).

Produces a natural, expert-toned operational narrative summarizing:
1. Raw alarm composition (alarm types, devices, network classes).
2. Chain WHY / descriptors (strong dimensions, dominant descriptors).
3. Topology mapping (mapped resources, verified resource types).
4. Structural audit findings (conductance, candidate cuts, partition status).
5. Counterfactual recommendations (split alternatives).
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any

from .grounded_llm import render_grounded

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CohesionNarrativeResult:
    chain_id: str
    narrative: str
    model: str
    provider_status: str | None
    context: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def extract_cohesion_context(
    service: Any,
    chain_id: str,
    analysis: Any | None = None,
    audit_artifact: Any | None = None,
    review_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract structured facts across the 5 authoritative data sources."""
    package = service.require_package()
    if analysis is None:
        analysis = service.analyze(chain_id)

    # -------------------------------------------------------------------------
    # 1. Raw Alarms of the Chain
    # -------------------------------------------------------------------------
    raw_alarms = package.alarms_of(chain_id)
    alarm_count = len(raw_alarms) if raw_alarms else getattr(analysis, "member_count", 1)

    alarm_names: list[str] = []
    network_classes: list[str] = []
    device_types: list[str] = []
    devices: list[str] = []
    start_times: list[str] = []

    for alarm in raw_alarms:
        raw = alarm.raw if hasattr(alarm, "raw") and isinstance(alarm.raw, dict) else {}
        name = alarm.alarm_name or raw.get("alarm_name") or "Unknown Alarm"
        dev = alarm.device_code or raw.get("device_code") or raw.get("device_name")
        dev_type = raw.get("device_type_name") or raw.get("device_type")
        net_class = raw.get("network_class_name") or raw.get("network_class")
        s_time = alarm.canonical_start_time or raw.get("cah.start_time") or raw.get("start_time")

        if name:
            alarm_names.append(name)
        if dev:
            devices.append(dev)
        if dev_type:
            device_types.append(dev_type)
        if net_class:
            network_classes.append(net_class)
        if s_time:
            start_times.append(s_time)

    # Top alarm types by frequency
    name_counts = Counter(alarm_names)
    top_alarm_types = [[name, count] for name, count in name_counts.most_common(3)]

    # Duration calculation
    duration_seconds: int = 0
    if hasattr(analysis, "duration_seconds") and analysis.duration_seconds is not None:
        duration_seconds = int(analysis.duration_seconds)
    elif start_times:
        try:
            import datetime
            parsed_times = [
                datetime.datetime.fromisoformat(t.replace("Z", "+00:00"))
                for t in start_times
                if t
            ]
            if len(parsed_times) >= 2:
                duration_seconds = int((max(parsed_times) - min(parsed_times)).total_seconds())
        except Exception:
            duration_seconds = 0

    # -------------------------------------------------------------------------
    # 2. Chain WHY / Descriptors
    # -------------------------------------------------------------------------
    strong_views: list[str] = []
    partial_views: list[str] = []

    # Check temporal burst: duration <= 60s
    if duration_seconds <= 60 and alarm_count > 1:
        strong_views.append("TEMPORAL_BURST")
    elif alarm_count > 1:
        partial_views.append("T_DELAY")

    # Check device concentration
    dev_counts = Counter(devices)
    if dev_counts:
        top_dev_share = dev_counts.most_common(1)[0][1] / max(1, alarm_count)
        if top_dev_share >= 0.6:
            strong_views.append("ENTITY_REFERENCE")
        else:
            partial_views.append("ENTITY_REFERENCE")

    descriptors = getattr(analysis, "descriptors", None)
    raw_desc: list[Any] = []
    if descriptors is not None:
        if hasattr(descriptors, "identity") and hasattr(descriptors, "contrastive"):
            raw_desc = [*getattr(descriptors, "identity", ()), *getattr(descriptors, "contrastive", ())]
        elif isinstance(descriptors, (list, tuple)):
            raw_desc = list(descriptors)

    top_descriptors: list[str] = []
    for d in raw_desc[:3]:
        lbl = getattr(d, "label", None) or (d.get("label") if isinstance(d, dict) else None)
        if lbl:
            top_descriptors.append(str(lbl))

    # -------------------------------------------------------------------------
    # 3. Topology Mapping
    # -------------------------------------------------------------------------
    member_ids = set(package.members_of(chain_id))
    mapped_count = 0
    resource_types: set[str] = set()

    for raw_mapping in package.topology.get("mappings") or ():
        if not isinstance(raw_mapping, dict):
            continue
        alarm_id = raw_mapping.get("alarm_id")
        if alarm_id in member_ids:
            mapped_count += 1
            res_type = raw_mapping.get("resource_type") or raw_mapping.get("type")
            if res_type:
                resource_types.add(str(res_type))

    # If no explicit mapping rows, derive resource types from device_types
    if not resource_types and device_types:
        resource_types.update(Counter(device_types).keys())

    if mapped_count > 0:
        strong_views.append("TOPOLOGY")
    elif alarm_count > 1:
        partial_views.append("TOPOLOGY")

    # -------------------------------------------------------------------------
    # 4. Audit Artifacts
    # -------------------------------------------------------------------------
    candidate_cut = False
    conductance: float | None = None
    audit_status = "SOLID"

    if audit_artifact is not None:
        scored_cuts = getattr(audit_artifact, "scored_cuts", ())
        best_cut_index = getattr(audit_artifact, "best_cut_index", None)
        if scored_cuts and len(scored_cuts) > 0:
            candidate_cut = True
            audit_status = "NEEDS_ATTENTION"
            if best_cut_index is not None and 0 <= best_cut_index < len(scored_cuts):
                best_cut = scored_cuts[best_cut_index]
                conductance = getattr(best_cut, "conductance", None)
            elif hasattr(scored_cuts[0], "conductance"):
                conductance = getattr(scored_cuts[0], "conductance", None)

    # -------------------------------------------------------------------------
    # 5. Counterfactual Recommendations
    # -------------------------------------------------------------------------
    split_recommended = False
    if isinstance(review_result, dict):
        for rec in review_result.get("recommendations", []):
            if isinstance(rec, dict) and rec.get("operation") == "SPLIT_CHAIN":
                split_recommended = True
                break

    return {
        "chain": {
            "chain_id": chain_id,
            "alarm_count": alarm_count,
            "duration_seconds": duration_seconds,
            "is_singleton": alarm_count == 1,
        },
        "alarm_summary": {
            "top_alarm_types": top_alarm_types,
            "network_classes": sorted(list(set(network_classes)))[:3],
            "device_types": sorted(list(set(device_types)))[:3],
            "devices": sorted(list(set(devices)))[:4],
        },
        "why": {
            "strong_views": strong_views,
            "partial_views": partial_views,
            "top_descriptors": top_descriptors,
        },
        "topology": {
            "mapped": mapped_count,
            "total": alarm_count,
            "resource_types": sorted(list(resource_types))[:4],
            "dependency_verified": False,
        },
        "audit": {
            "status": audit_status,
            "candidate_cut": candidate_cut,
            "conductance": round(conductance, 3) if conductance is not None else None,
        },
        "recommendations": {
            "split_recommended": split_recommended,
        },
    }


def build_deterministic_cohesion_narrative(context: dict[str, Any]) -> str:
    """Compose a fluent, natural domain-expert narrative from structured facts."""
    chain = context.get("chain", {})
    alarm_summary = context.get("alarm_summary", {})
    topology = context.get("topology", {})
    audit = context.get("audit", {})
    recs = context.get("recommendations", {})

    chain_id = chain.get("chain_id", "Unknown")
    alarm_count = chain.get("alarm_count", 1)
    is_singleton = chain.get("is_singleton", False)
    top_alarms = alarm_summary.get("top_alarm_types", [])
    network_classes = alarm_summary.get("network_classes", [])
    devices = alarm_summary.get("devices", [])
    res_types = topology.get("resource_types", [])
    candidate_cut = audit.get("candidate_cut", False)
    conductance = audit.get("conductance")
    split_recommended = recs.get("split_recommended", False)

    # 1. Singleton narrative
    if is_singleton:
        alarm_name = top_alarms[0][0] if top_alarms else "alarm event"
        dev = devices[0] if devices else "target device"
        net = f" on {network_classes[0]}" if network_classes else ""
        return (
            f"This is an isolated single-alarm event for '{alarm_name}' on {dev}{net}. "
            "Evidence indicates a localized symptom with no cross-device temporal propagation."
        )

    # 2. Multi-alarm composition sentence
    net_str = f"{', '.join(network_classes)} " if network_classes else ""
    if top_alarms:
        primary_name = top_alarms[0][0]
        primary_count = top_alarms[0][1]
        secondary_name = top_alarms[1][0] if len(top_alarms) > 1 else None

        if primary_count == alarm_count:
            composition_clause = f"dominated entirely by {alarm_count} '{primary_name}' events"
        elif secondary_name:
            composition_clause = (
                f"predominantly composed of {primary_count} '{primary_name}' events "
                f"alongside '{secondary_name}'"
            )
        else:
            composition_clause = f"primarily composed of {primary_count} '{primary_name}' events"
    else:
        composition_clause = f"composed of {alarm_count} correlated alarms"

    dev_clause = f" across {len(devices)} device(s) ({', '.join(devices[:2])})" if devices else ""
    res_clause = f" covering {', '.join(res_types[:2])} infrastructure" if res_types else ""

    sentence_1 = f"Chain {chain_id} is a {net_str}cluster {composition_clause}{dev_clause}{res_clause}."

    # 3. Structural audit & recommendation sentence
    if split_recommended:
        sentence_2 = (
            "A structural partition boundary was identified, and a split alternative "
            "has been recommended for review."
        )
    elif candidate_cut:
        cond_str = f" (conductance {conductance:.2f})" if conductance is not None else ""
        sentence_2 = (
            f"Structural audit detected a weak separation boundary between member groups{cond_str}, "
            "though no split alternative is currently recommended."
        )
    else:
        sentence_2 = "Structural audit confirms high cohesion with no partition boundaries detected."

    return f"{sentence_1} {sentence_2}"


def generate_cohesion_narrative(
    service: Any,
    chain_id: str,
    audit_artifact: Any | None = None,
    review_result: dict[str, Any] | None = None,
) -> CohesionNarrativeResult:
    """Generate a grounded narrative, optionally polished by an LLM."""
    package = service.require_package()
    analysis = service.analyze(chain_id)

    # Extract 5 sources context
    context = extract_cohesion_context(
        service=service,
        chain_id=chain_id,
        analysis=analysis,
        audit_artifact=audit_artifact,
        review_result=review_result,
    )

    deterministic_draft = build_deterministic_cohesion_narrative(context)

    # Prepare grounding claims
    claims: list[str] = [
        f"Chain ID: {chain_id}",
        f"Alarm count: {context['chain']['alarm_count']}",
        f"Duration seconds: {context['chain']['duration_seconds']}",
    ]
    if context["alarm_summary"]["top_alarm_types"]:
        for name, cnt in context["alarm_summary"]["top_alarm_types"]:
            claims.append(f"Alarm type: {name} (count: {cnt})")
    if context["alarm_summary"]["network_classes"]:
        claims.append(f"Network classes: {', '.join(context['alarm_summary']['network_classes'])}")
    if context["topology"]["resource_types"]:
        claims.append(f"Topology resources: {', '.join(context['topology']['resource_types'])}")
    claims.append(f"Candidate cut detected: {context['audit']['candidate_cut']}")
    claims.append(f"Split recommended: {context['recommendations']['split_recommended']}")

    # System instruction tailored for natural, non-stiff tone
    prompt_facts = {
        "context": context,
        "instruction": (
            "Write 1-2 fluent, concise, natural sentences summarizing the alarm composition, "
            "domain context, and boundary audit for this alarm chain. Follow ADR-0024: use ONLY "
            "the provided structured facts. Never fabricate unverified DWDM, passive fiber breaks, "
            "or root cause. The tone must be natural and professional, not stiff database listings."
        ),
    }

    try:
        rendered = render_grounded(
            draft=deterministic_draft,
            facts=prompt_facts,
            fact_refs=claims,
            purpose="ADVISOR",
        )
        return CohesionNarrativeResult(
            chain_id=chain_id,
            narrative=rendered.message,
            model=rendered.model,
            provider_status=rendered.provider_status,
            context=context,
        )
    except Exception as exc:
        logger.warning("LLM render failed, falling back to deterministic narrative: %s", exc)
        return CohesionNarrativeResult(
            chain_id=chain_id,
            narrative=deterministic_draft,
            model="DETERMINISTIC_EVIDENCE",
            provider_status="UNAVAILABLE",
            context=context,
        )
