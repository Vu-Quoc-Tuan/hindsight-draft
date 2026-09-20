"""Topology-aware Alarm Entity Resolution.

Resolves entities mentioned in alarms (observed host, affected component candidates,
mentioned dependencies) into topology resources with provenance, confidence, and status.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from contracts.v1.enums import MappingMethod, MappingStatus
from contracts.v1.models import AlarmEntityResolution


@dataclass(frozen=True)
class ModuleCandidate:
    resource_id: str
    display_name: str
    base_token: str
    host_ip: str | None = None


def normalize_token(text: str) -> str:
    """Normalize text for token comparison: lowercase, replace underscores/spaces with hyphens."""
    if not text:
        return ""
    return re.sub(r"[_\s]+", "-", text.strip().lower())


def extract_base_module_token(display_name: str) -> str:
    """Extract the base service/module name from topology module display_name.

    e.g. 'nova-compute_10.210.48.81' -> 'nova-compute'
    e.g. 'neutron-openvswitch-agent_10.210.48.81' -> 'neutron-openvswitch-agent'
    e.g. 'kolla-toolbox_10.210.48.81' -> 'kolla-toolbox'
    """
    parts = display_name.split("_")
    raw_token = parts[0] if parts else display_name
    return normalize_token(raw_token)


class AlarmEntityResolver:
    """Resolves alarm entities into topology resources with explicit role and status."""

    def __init__(
        self,
        *,
        profile_id: str = "IT_SERVICES",
        topology_version: str | None = None,
        resolver_version: str = "v1",
        host_modules_map: dict[str, list[ModuleCandidate]] | None = None,
        host_canonical_id_map: dict[str, str] | None = None,
    ) -> None:
        self.profile_id = profile_id
        self.topology_version = topology_version
        self.resolver_version = resolver_version
        self.host_modules_map = host_modules_map or {}
        self.host_canonical_id_map = host_canonical_id_map or {}

    def resolve_alarm(
        self,
        alarm_id: str,
        *,
        raw_content: str | None = None,
        alarm_name: str | None = None,
        device_code: str | None = None,
        node_reference: str | None = None,
        raw_fields: Mapping[str, Any] | None = None,
    ) -> tuple[str | None, list[AlarmEntityResolution]]:
        """Resolve an alarm into (observed_resource_id, list[AlarmEntityResolution])."""
        raw = dict(raw_fields or {})
        resolutions: list[AlarmEntityResolution] = []

        # 1. Identify observed host IP / code
        raw_ip = raw.get("device_ip") or raw.get("ip") or device_code or node_reference or ""
        clean_ip = raw_ip.strip().split("/")[0] if raw_ip else ""

        observed_resource_id: str | None = None
        if clean_ip:
            canonical_host_id = self.host_canonical_id_map.get(clean_ip)
            if canonical_host_id:
                observed_resource_id = canonical_host_id
                resolutions.append(
                    AlarmEntityResolution(
                        alarm_id=alarm_id,
                        entity_role="OBSERVED_HOST",
                        raw_value=clean_ip,
                        resource_id=canonical_host_id,
                        status=MappingStatus.EXACT,
                        method=MappingMethod.EXACT_IDENTITY,
                        source_field="device_ip" if (raw.get("device_ip") or raw.get("ip")) else "device_code",
                        confidence=1.0,
                        topology_profile_id=self.profile_id,
                        topology_version=self.topology_version,
                        candidate_resource_ids=(canonical_host_id,),
                        matched_text=clean_ip,
                        resolver_version=self.resolver_version,
                    )
                )
            else:
                resolutions.append(
                    AlarmEntityResolution(
                        alarm_id=alarm_id,
                        entity_role="OBSERVED_HOST",
                        raw_value=clean_ip,
                        resource_id=None,
                        status=MappingStatus.UNMAPPED,
                        method=MappingMethod.NONE,
                        source_field="device_ip" if (raw.get("device_ip") or raw.get("ip")) else "device_code",
                        confidence=0.0,
                        topology_profile_id=self.profile_id,
                        topology_version=self.topology_version,
                        candidate_resource_ids=(),
                        matched_text="",
                        resolver_version=self.resolver_version,
                    )
                )

        # 2. Host-scoped module candidates
        candidates = self.host_modules_map.get(clean_ip) or []
        if not candidates and observed_resource_id:
            candidates = self.host_modules_map.get(observed_resource_id) or []

        # 3. Check structured component/port field
        raw_component = raw.get("component") or raw.get("port")
        component_source_field = "component" if raw.get("component") else "port"
        structured_resolved = False
        if raw_component and str(raw_component).strip():
            comp_str = str(raw_component).strip()
            # If component is not simply the host IP itself
            if comp_str.split("/")[0] != clean_ip:
                norm_comp = normalize_token(comp_str)
                exact_base_matches = [m for m in candidates if m.base_token == norm_comp]
                if len(exact_base_matches) == 1:
                    m = exact_base_matches[0]
                    structured_resolved = True
                    resolutions.append(
                        AlarmEntityResolution(
                            alarm_id=alarm_id,
                            entity_role="AFFECTED_COMPONENT_CANDIDATE",
                            raw_value=comp_str,
                            resource_id=m.resource_id,
                            status=MappingStatus.STRUCTURED_FIELD_UNIQUE,
                            method=MappingMethod.STRUCTURED_FIELD_EXACT,
                            source_field=component_source_field,
                            confidence=0.85,
                            topology_profile_id=self.profile_id,
                            topology_version=self.topology_version,
                            candidate_resource_ids=(m.resource_id,),
                            matched_text=m.base_token,
                            resolver_version=self.resolver_version,
                        )
                    )
                elif len(exact_base_matches) > 1:
                    structured_resolved = True
                    resolutions.append(
                        AlarmEntityResolution(
                            alarm_id=alarm_id,
                            entity_role="AFFECTED_COMPONENT_CANDIDATE",
                            raw_value=comp_str,
                            resource_id=None,
                            status=MappingStatus.AMBIGUOUS,
                            method=MappingMethod.STRUCTURED_FIELD_EXACT,
                            source_field=component_source_field,
                            confidence=0.50,
                            topology_profile_id=self.profile_id,
                            topology_version=self.topology_version,
                            candidate_resource_ids=tuple(m.resource_id for m in exact_base_matches),
                            matched_text=", ".join(m.base_token for m in exact_base_matches),
                            resolver_version=self.resolver_version,
                        )
                    )
                else:
                    substr_matches = [m for m in candidates if norm_comp in normalize_token(m.display_name)]
                    if len(substr_matches) == 1:
                        m = substr_matches[0]
                        structured_resolved = True
                        resolutions.append(
                            AlarmEntityResolution(
                                alarm_id=alarm_id,
                                entity_role="AFFECTED_COMPONENT_CANDIDATE",
                                raw_value=comp_str,
                                resource_id=m.resource_id,
                                status=MappingStatus.TEXT_MATCH_CANDIDATE,
                                method=MappingMethod.STRUCTURED_FIELD_EXACT,
                                source_field=component_source_field,
                                confidence=0.60,
                                topology_profile_id=self.profile_id,
                                topology_version=self.topology_version,
                                candidate_resource_ids=(m.resource_id,),
                                matched_text=m.display_name,
                                resolver_version=self.resolver_version,
                            )
                        )
                    elif len(substr_matches) > 1:
                        structured_resolved = True
                        resolutions.append(
                            AlarmEntityResolution(
                                alarm_id=alarm_id,
                                entity_role="AFFECTED_COMPONENT_CANDIDATE",
                                raw_value=comp_str,
                                resource_id=None,
                                status=MappingStatus.AMBIGUOUS,
                                method=MappingMethod.STRUCTURED_FIELD_EXACT,
                                source_field=component_source_field,
                                confidence=0.40,
                                topology_profile_id=self.profile_id,
                                topology_version=self.topology_version,
                                candidate_resource_ids=tuple(m.resource_id for m in substr_matches),
                                matched_text=", ".join(m.base_token for m in substr_matches),
                                resolver_version=self.resolver_version,
                            )
                        )

        # 4. Fallback: Host-scoped dynamic vocabulary matching in raw text
        if not structured_resolved and candidates:
            search_text = f"{alarm_name or ''} {raw_content or ''}"
            norm_search = normalize_token(search_text)

            # Sort candidate tokens by length descending to match longest specific names first
            sorted_candidates = sorted(candidates, key=lambda c: len(c.base_token), reverse=True)
            matched_candidates: list[tuple[ModuleCandidate, str]] = []

            for cand in sorted_candidates:
                token = cand.base_token
                # Skip trivial or generic stop words
                if len(token) < 3 or token in ("app", "api", "web", "sys", "srv", "node"):
                    continue
                # Word boundary match with hyphen/underscore equivalence
                pattern = r"(?:\b|_)" + re.escape(token) + r"(?:\b|_)"
                match = re.search(pattern, norm_search)
                if match:
                    matched_candidates.append((cand, token))

            if len(matched_candidates) == 1:
                cand, token = matched_candidates[0]
                resolutions.append(
                    AlarmEntityResolution(
                        alarm_id=alarm_id,
                        entity_role="AFFECTED_COMPONENT_CANDIDATE",
                        raw_value=token,
                        resource_id=cand.resource_id,
                        status=MappingStatus.TEXT_MATCH_CANDIDATE,
                        method=MappingMethod.RAW_TEXT_EXACT_TOKEN,
                        source_field="content" if raw_content and token in normalize_token(raw_content) else "alarm_name",
                        confidence=0.72,
                        topology_profile_id=self.profile_id,
                        topology_version=self.topology_version,
                        candidate_resource_ids=(cand.resource_id,),
                        matched_text=token,
                        resolver_version=self.resolver_version,
                    )
                )
            elif len(matched_candidates) > 1:
                # Disambiguate if one candidate is a strict prefix/substring of another (e.g. nova vs nova-compute)
                distinct_candidates: list[tuple[ModuleCandidate, str]] = []
                for cand, token in matched_candidates:
                    is_substring = any(
                        token != other_token and token in other_token
                        for _, other_token in matched_candidates
                    )
                    if not is_substring:
                        distinct_candidates.append((cand, token))

                if len(distinct_candidates) == 1:
                    cand, token = distinct_candidates[0]
                    resolutions.append(
                        AlarmEntityResolution(
                            alarm_id=alarm_id,
                            entity_role="AFFECTED_COMPONENT_CANDIDATE",
                            raw_value=token,
                            resource_id=cand.resource_id,
                            status=MappingStatus.TEXT_MATCH_CANDIDATE,
                            method=MappingMethod.RAW_TEXT_EXACT_TOKEN,
                            source_field="content" if raw_content and token in normalize_token(raw_content) else "alarm_name",
                            confidence=0.72,
                            topology_profile_id=self.profile_id,
                            topology_version=self.topology_version,
                            candidate_resource_ids=(cand.resource_id,),
                            matched_text=token,
                            resolver_version=self.resolver_version,
                        )
                    )
                else:
                    # Multiple distinct modules truly matched! Keep all candidates as AMBIGUOUS.
                    cand_ids = tuple(c.resource_id for c, _ in distinct_candidates)
                    tokens = ", ".join(t for _, t in distinct_candidates)
                    resolutions.append(
                        AlarmEntityResolution(
                            alarm_id=alarm_id,
                            entity_role="AFFECTED_COMPONENT_CANDIDATE",
                            raw_value=tokens,
                            resource_id=None,
                            status=MappingStatus.AMBIGUOUS,
                            method=MappingMethod.RAW_TEXT_EXACT_TOKEN,
                            source_field="content" if raw_content and any(t in normalize_token(raw_content) for _, t in distinct_candidates) else "alarm_name",
                            confidence=0.40,
                            topology_profile_id=self.profile_id,
                            topology_version=self.topology_version,
                            candidate_resource_ids=cand_ids,
                            matched_text=tokens,
                            resolver_version=self.resolver_version,
                        )
                    )

        return observed_resource_id, resolutions

    @classmethod
    def from_package(cls, package: Any, profile_id: str = "IT_SERVICES") -> AlarmEntityResolver:
        """Construct an in-memory resolver from a package's topology."""
        topology = getattr(package, "topology", None) or {}
        nodes = getattr(topology, "nodes", ()) if hasattr(topology, "nodes") else ()
        edges = getattr(topology, "edges", ()) if hasattr(topology, "edges") else ()
        if isinstance(topology, dict):
            nodes = topology.get("nodes", ())
            edges = topology.get("edges", ())

        host_modules_map: dict[str, list[ModuleCandidate]] = {}
        host_canonical_id_map: dict[str, str] = {}
        id_to_ip: dict[str, str] = {}

        for n in nodes:
            res_id = getattr(n, "resource_id", None) or (n.get("resource_id") or n.get("id") if isinstance(n, dict) else None)
            res_type = getattr(n, "resource_type", None) or (n.get("resource_type") or n.get("type") if isinstance(n, dict) else None)
            disp_name = getattr(n, "display_name", None) or (n.get("display_name") or n.get("name") if isinstance(n, dict) else None) or ""
            if res_id and (res_type == "INSTANCE" or "instance" in str(res_id).lower()):
                clean_ip = disp_name.split("/")[0].strip() if disp_name else res_id.split(":")[-1]
                if clean_ip:
                    host_canonical_id_map[clean_ip] = res_id
                    id_to_ip[res_id] = clean_ip

        for e in edges:
            src = getattr(e, "source_id", None) or (e.get("source_id") or e.get("source") if isinstance(e, dict) else None)
            tgt = getattr(e, "target_id", None) or (e.get("target_id") or e.get("target") if isinstance(e, dict) else None)
            rel = getattr(e, "relation_type", None) or (e.get("relation_type") or e.get("relation") if isinstance(e, dict) else None) or ""
            if src and tgt and "MODULE_HAS_INSTANCE" in str(rel):
                mod_name = src
                for n in nodes:
                    nid = getattr(n, "resource_id", None) or (n.get("resource_id") or n.get("id") if isinstance(n, dict) else None)
                    if nid == src:
                        mod_name = getattr(n, "display_name", None) or (n.get("display_name") or n.get("name") if isinstance(n, dict) else None) or src
                        break
                base_tok = extract_base_module_token(mod_name)
                cand = ModuleCandidate(
                    resource_id=src,
                    display_name=mod_name,
                    base_token=base_tok,
                    host_ip=id_to_ip.get(tgt),
                )
                host_modules_map.setdefault(tgt, []).append(cand)
                if tgt in id_to_ip:
                    host_modules_map.setdefault(id_to_ip[tgt], []).append(cand)

        return cls(
            profile_id=profile_id,
            host_modules_map=host_modules_map,
            host_canonical_id_map=host_canonical_id_map,
        )
