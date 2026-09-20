"""Contrastive analysis: ``U_local``, CONTRASTIVE descriptors, ``Margin_common`` (§4B/§5).

    U_local(C)              top-k competing chains from the blocking index
    G_common(x; C, C')      groups available for both chains
    Margin_common(x)        mean over G_common of [Fit_g(x,C) - Fit_g(x,C')]
    |G_common| < g_min      => INSUFFICIENT CONTRASTIVE EVIDENCE

``U_local`` has a hard definition: the top-k competing chains from the blocking
index, which is exactly the contrastive candidate set. It is not "everything
else", because a global complement would make local precision meaningless.

``Margin_common`` is only averaged over groups computable in **both** chains.
Comparing a group available in C against ⊥ in C' would compare evidence with
absence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from libs.contracts import IngestedPackage

from groups.fit import GroupFit
from groups.statistics import ChannelStatistics

#: Default number of competing chains in U_local (descriptor mining universe).
DEFAULT_U_LOCAL_K = 5

#: WHY-4 contrastive panel bound (§5, §11): exactly top-3 candidates, not the
#: whole U_local. This is a VISUALIZATION-facing bound, distinct from
#: DEFAULT_U_LOCAL_K which sizes the STATISTICAL/mining universe.
DEFAULT_CONTRASTIVE_TOP_K = 3

#: Minimum shared groups for a contrastive verdict.
DEFAULT_G_MIN = 2


@dataclass(frozen=True)
class BlockingCandidate:
    """One competing chain plus the blocking key that surfaced it."""

    chain_id: str
    shared_key: str
    shared_value: str
    overlap: int


# Causal propagation keyword sets for Cross-Domain / Cross-Layer candidate discovery
CAUSAL_ROOT_KEYWORDS: frozenset[str] = frozenset({
    "POWER", "AC_FAIL", "DC_FAIL", "BATTERY", "RECTIFIER", "GENERATOR", "UPS",
    "HIGH_TEMP", "FAN_FAIL", "OPTICAL", "FIBER", "LASER", "ETH_LOS", "LOS",
    "LOF", "AIS", "PHYSICAL_DOWN", "SYNCHRONIZATION", "SYNC", "E1", "CLOCK",
    "TRANSMISSION", "TRUNK", "LINK_DOWN",
})

CAUSAL_SYMPTOM_KEYWORDS: frozenset[str] = frozenset({
    "BGP", "OSPF", "ISIS", "INTERFACE_DOWN", "SESSION_DOWN", "PORT_DOWN",
    "CELL", "SECTOR", "CARRIER", "S1_INTERFACE", "RADIO", "ENODEB", "GNB",
    "NODEB", "FAIL", "DOWN", "UNAVAILABLE", "UNREACHABLE", "OUT_OF_SERVICE",
    "OFFLINE", "DISCONNECTED", "NE_COMMUNICATION_OUT",
})


import re


def _matches_keywords(alarm_name: str | None, keywords: frozenset[str]) -> bool:
    if not alarm_name:
        return False
    upper = alarm_name.upper()
    tokens = set(re.split(r'[^A-Z0-9]+', upper))
    for kw in keywords:
        if "_" in kw:
            if kw in upper:
                return True
        else:
            if kw in tokens:
                return True
    return False


def _topology_candidate_scores(
    package: IngestedPackage,
    chain_id: str,
    target_members: set[str],
) -> dict[str, tuple[str, str, int]]:
    """Discover candidate chains sharing topological links (direct or up to 2 hops)."""
    topo = getattr(package, "topology", None)
    if not topo:
        return {}

    edges = topo.get("edges") if isinstance(topo, dict) else getattr(topo, "edges", ())
    mappings = topo.get("mappings") if isinstance(topo, dict) else getattr(topo, "mappings", ())
    edges = edges or ()
    mappings = mappings or ()

    # Map alarm_id -> resource_id
    alarm_to_resource: dict[str, str] = {}
    for m in mappings:
        aid = m.get("alarm_id") if isinstance(m, dict) else getattr(m, "alarm_id", None)
        rid = m.get("resource_id") if isinstance(m, dict) else getattr(m, "resource_id", None)
        status = m.get("mapping_status") if isinstance(m, dict) else getattr(m, "mapping_status", None)
        if aid and rid and status in ("EXACT", "VERIFIED_ALIAS", None):
            alarm_to_resource[aid] = str(rid)

    # Build resource adjacency graph
    adj: dict[str, set[str]] = {}
    for e in edges:
        s = e.get("source_resource_id") if isinstance(e, dict) else getattr(e, "source_resource_id", None)
        t = e.get("target_resource_id") if isinstance(e, dict) else getattr(e, "target_resource_id", None)
        if s and t:
            s_str, t_str = str(s), str(t)
            adj.setdefault(s_str, set()).add(t_str)
            adj.setdefault(t_str, set()).add(s_str)

    # Collect target chain resources
    target_resources: set[str] = set()
    for aid in target_members:
        alarm = package.alarms.get(aid)
        res = alarm_to_resource.get(aid)
        if not res and alarm:
            res = alarm.device_code or alarm.node_reference or (alarm.raw.get("device_code") if getattr(alarm, "raw", None) else None)
        if res:
            target_resources.add(str(res))

    if not target_resources:
        return {}

    # Expand 1-hop and 2-hop neighbors
    neighbors_1hop = {nbr for r in target_resources for nbr in adj.get(r, ()) if nbr not in target_resources}
    neighbors_2hop = {nbr2 for nbr in neighbors_1hop for nbr2 in adj.get(nbr, ()) if nbr2 not in target_resources and nbr2 not in neighbors_1hop}

    topo_scores: dict[str, tuple[str, str, int]] = {}
    for other_chain, other_members in package.memberships.items():
        if other_chain == chain_id:
            continue
        score = 0
        best_match = ""
        for aid in other_members:
            alarm = package.alarms.get(aid)
            res = alarm_to_resource.get(aid)
            if not res and alarm:
                res = alarm.device_code or alarm.node_reference or (alarm.raw.get("device_code") if getattr(alarm, "raw", None) else None)
            if not res:
                continue
            res_str = str(res)

            if res_str in target_resources:
                score += 8  # Same device / resource
                best_match = f"same_device:{res_str}"
            elif res_str in neighbors_1hop:
                score += 5  # Direct 1-hop link
                if not best_match or "same_device" not in best_match:
                    best_match = f"1hop:{res_str}"
            elif res_str in neighbors_2hop:
                score += 2  # 2-hop link
                if not best_match:
                    best_match = f"2hop:{res_str}"

        if score > 0:
            topo_scores[other_chain] = ("topology_adjacency", best_match or "topo_linked", score)

    return topo_scores


def _temporal_candidate_scores(
    package: IngestedPackage,
    chain_id: str,
    target_members: set[str],
    window_seconds: int = 120,
) -> dict[str, tuple[str, str, int]]:
    """Discover candidate chains co-occurring within the same temporal blast radius."""
    from datetime import datetime

    def parse_time(alarm) -> datetime | None:
        if not alarm:
            return None
        val = getattr(alarm, "canonical_start_time", None) or (alarm.raw.get("occur_time") if getattr(alarm, "raw", None) else None)
        if not val:
            return None
        try:
            dt = datetime.fromisoformat(str(val).replace(" ", "T"))
            return dt.replace(tzinfo=None)
        except (ValueError, TypeError):
            return None

    target_times: list[datetime] = []
    target_bursts: set[str] = set()
    for aid in target_members:
        alarm = package.alarms.get(aid)
        if not alarm:
            continue
        t = parse_time(alarm)
        if t:
            target_times.append(t)
        bid = alarm.raw.get("burst_id") if getattr(alarm, "raw", None) else None
        if bid:
            target_bursts.add(str(bid))

    if not target_times and not target_bursts:
        return {}

    min_t = min(target_times) if target_times else None
    max_t = max(target_times) if target_times else None

    temporal_scores: dict[str, tuple[str, str, int]] = {}
    for other_chain, other_members in package.memberships.items():
        if other_chain == chain_id:
            continue
        score = 0
        matching_burst: str | None = None
        for aid in other_members:
            alarm = package.alarms.get(aid)
            if not alarm:
                continue
            bid = alarm.raw.get("burst_id") if getattr(alarm, "raw", None) else None
            if bid and str(bid) in target_bursts:
                score += 4
                matching_burst = str(bid)
            elif min_t and max_t:
                t = parse_time(alarm)
                if t:
                    delta = (t - max_t).total_seconds() if t > max_t else (min_t - t).total_seconds() if t < min_t else 0
                    if delta <= window_seconds:
                        score += 2

        if score > 0:
            val_desc = f"burst:{matching_burst}" if matching_burst else f"window_{window_seconds}s"
            temporal_scores[other_chain] = ("temporal_burst", val_desc, score)

    return temporal_scores


def _semantic_causal_candidate_scores(
    package: IngestedPackage,
    chain_id: str,
    target_members: set[str],
    taxonomy: Any = None,
) -> dict[str, tuple[str, str, int]]:
    """Discover candidate chains with semantic family matches or causal propagation links."""
    target_names: set[str] = set()
    has_root = False
    has_symptom = False

    for aid in target_members:
        alarm = package.alarms.get(aid)
        if not alarm:
            continue
        name = getattr(alarm, "alarm_name", None) or (alarm.raw.get("alarm_name") if getattr(alarm, "raw", None) else None)
        if name:
            target_names.add(str(name))
            if _matches_keywords(str(name), CAUSAL_ROOT_KEYWORDS):
                has_root = True
            if _matches_keywords(str(name), CAUSAL_SYMPTOM_KEYWORDS):
                has_symptom = True

    if not target_names:
        return {}

    semantic_scores: dict[str, tuple[str, str, int]] = {}
    for other_chain, other_members in package.memberships.items():
        if other_chain == chain_id:
            continue
        score = 0
        causal_match = ""
        for aid in other_members:
            alarm = package.alarms.get(aid)
            if not alarm:
                continue
            name = getattr(alarm, "alarm_name", None) or (alarm.raw.get("alarm_name") if getattr(alarm, "raw", None) else None)
            if not name:
                continue
            name_str = str(name)

            if taxonomy:
                fam = taxonomy.family_of(name_str) if hasattr(taxonomy, "family_of") else None
                cat = taxonomy.category_of(name_str) if hasattr(taxonomy, "category_of") else None
                if fam and any(hasattr(taxonomy, "family_of") and taxonomy.family_of(tn) == fam for tn in target_names):
                    score += 3
                    causal_match = f"same_family:{fam}"
                elif cat and any(hasattr(taxonomy, "category_of") and taxonomy.category_of(tn) == cat for tn in target_names):
                    score += 2
                    causal_match = f"same_category:{cat}"

            is_other_root = _matches_keywords(name_str, CAUSAL_ROOT_KEYWORDS)
            is_other_symptom = _matches_keywords(name_str, CAUSAL_SYMPTOM_KEYWORDS)

            if has_root and is_other_symptom:
                score += 4
                causal_match = "causal_root_to_symptom"
            elif has_symptom and is_other_root:
                score += 4
                causal_match = "causal_symptom_from_root"

        if score > 0:
            semantic_scores[other_chain] = ("semantic_causal", causal_match or "semantic_relation", score)

    return semantic_scores


def blocking_candidates(
    package: IngestedPackage,
    chain_id: str,
    *,
    blocking_fields: tuple[str, ...] = ("location_code", "network_class_name", "alarm_name"),
    k: int = DEFAULT_U_LOCAL_K,
    include_topology: bool = True,
    include_temporal: bool = True,
    include_semantic: bool = True,
    taxonomy: Any = None,
) -> list[BlockingCandidate]:
    """Find the top-k competing chains via a multi-dimensional blocking index.

    Combines:
    1. Structured attribute matching (location, network class, alarm name).
    2. Topology adjacency (direct and multi-hop link neighbors).
    3. Temporal burst / window correlation (co-occurring within blast radius).
    4. Semantic and causal relation propagation (cause-symptom patterns).
    """
    from descriptor.predicates import read_field

    members = set(package.members_of(chain_id))
    if not members:
        return []

    target_values: dict[str, set[str]] = {}
    for alarm_id in members:
        alarm = package.alarms.get(alarm_id)
        if alarm is None:
            continue
        for field in blocking_fields:
            value = read_field(alarm, field)
            if value:
                target_values.setdefault(field, set()).add(value)

    # 1. Attribute-based scores
    attr_scores: dict[tuple[str, str, str], int] = {}
    for other_chain, other_members in package.memberships.items():
        if other_chain == chain_id:
            continue
        for alarm_id in other_members:
            alarm = package.alarms.get(alarm_id)
            if alarm is None:
                continue
            for field in blocking_fields:
                value = read_field(alarm, field)
                if value and value in target_values.get(field, ()):
                    key = (other_chain, field, value)
                    attr_scores[key] = attr_scores.get(key, 0) + 1

    # 2. Topology adjacency scores
    topo_scores = (
        _topology_candidate_scores(package, chain_id, members)
        if include_topology
        else {}
    )

    # 3. Temporal burst scores
    temporal_scores = (
        _temporal_candidate_scores(package, chain_id, members)
        if include_temporal
        else {}
    )

    # 4. Semantic / causal scores
    semantic_scores = (
        _semantic_causal_candidate_scores(package, chain_id, members, taxonomy=taxonomy)
        if include_semantic
        else {}
    )

    all_other_chains = set()
    for other_chain, _, _ in attr_scores:
        all_other_chains.add(other_chain)
    all_other_chains.update(topo_scores.keys())
    all_other_chains.update(temporal_scores.keys())
    all_other_chains.update(semantic_scores.keys())

    best: dict[str, BlockingCandidate] = {}
    for other_chain in all_other_chains:
        best_attr_field = None
        best_attr_val = None
        best_attr_score = 0
        for (c, f, v), count in attr_scores.items():
            if c == other_chain and count > best_attr_score:
                best_attr_field = f
                best_attr_val = v
                best_attr_score = count

        topo_entry = topo_scores.get(other_chain)
        temp_entry = temporal_scores.get(other_chain)
        sem_entry = semantic_scores.get(other_chain)

        topo_weight = topo_entry[2] if topo_entry else 0
        temp_weight = temp_entry[2] if temp_entry else 0
        sem_weight = sem_entry[2] if sem_entry else 0

        total_overlap = best_attr_score + topo_weight + temp_weight + sem_weight

        primary_key = best_attr_field or "attribute"
        primary_val = best_attr_val or "match"

        max_subscore = best_attr_score
        if topo_weight > max_subscore:
            primary_key, primary_val, max_subscore = topo_entry[0], topo_entry[1], topo_weight
        if sem_weight > max_subscore:
            primary_key, primary_val, max_subscore = sem_entry[0], sem_entry[1], sem_weight
        if temp_weight > max_subscore:
            primary_key, primary_val, max_subscore = temp_entry[0], temp_entry[1], temp_weight

        best[other_chain] = BlockingCandidate(
            chain_id=other_chain,
            shared_key=primary_key,
            shared_value=primary_val,
            overlap=total_overlap,
        )

    ranked = sorted(
        best.values(), key=lambda c: (-c.overlap, c.chain_id)
    )
    return ranked[:k]


def top_contrastive_candidates(
    candidates: tuple[BlockingCandidate, ...] | list[BlockingCandidate],
    *,
    top_k: int = DEFAULT_CONTRASTIVE_TOP_K,
) -> tuple[BlockingCandidate, ...]:
    """Bound the WHY-4 panel to exactly top-3 (§5, §11), never the whole U_local.

    ``candidates`` is already ranked by blocking overlap (see
    :func:`blocking_candidates`), so this takes a prefix rather than re-sorting
    -- ranking logic has exactly one place to live.
    """
    return tuple(candidates[:top_k])


def local_universe_bitmap(
    package: IngestedPackage,
    candidates: list[BlockingCandidate],
    index,
    *,
    target_chain_id: str,
) -> int:
    """``U_local`` bitmap: the target chain plus its top-k competitors.

    The target chain **must** be included. ``Precision_local`` asks "of the
    alarms in this local neighbourhood that match the rule, how many are in C?",
    so excluding C would force TP to zero and make every local precision 0.0.

    This is the frame that makes "globally common, locally discriminative" work:
    DIAMETER has 8% global precision but 95% precision inside ``U_local``.
    """
    from descriptor.predicates import bitmap_of_members

    member_ids: set[str] = set(package.members_of(target_chain_id))
    for candidate in candidates:
        member_ids.update(package.members_of(candidate.chain_id))
    return bitmap_of_members(index, member_ids)


@dataclass(frozen=True)
class MarginResult:
    """``Margin_common(x)`` plus the evidence behind it."""

    alarm_id: str
    #: ``None`` when there is insufficient contrastive evidence.
    margin: float | None
    shared_groups: int
    compared_chain_id: str | None
    insufficient: bool
    reason: str | None = None


def _role_fits(group_fits: tuple[GroupFit, ...]) -> dict[str, float]:
    """Computable role-eligible fits, keyed by derivation tag."""
    return {
        gf.derivation_tag: gf.fit
        for gf in group_fits
        if gf.role_eligible and gf.fit is not None
    }


def margin_common(
    alarm_id: str,
    own_fits: tuple[GroupFit, ...],
    rival_fits: tuple[GroupFit, ...],
    *,
    compared_chain_id: str | None,
    g_min: int = DEFAULT_G_MIN,
) -> MarginResult:
    """Compute ``Margin_common`` over groups available in both chains."""
    own = _role_fits(own_fits)
    rival = _role_fits(rival_fits)
    shared = sorted(set(own) & set(rival))

    if len(shared) < g_min:
        return MarginResult(
            alarm_id=alarm_id,
            margin=None,
            shared_groups=len(shared),
            compared_chain_id=compared_chain_id,
            insufficient=True,
            reason=(
                f"only {len(shared)} shared computable group(s); need >= {g_min}"
            ),
        )

    differences = [own[tag] - rival[tag] for tag in shared]
    return MarginResult(
        alarm_id=alarm_id,
        margin=sum(differences) / len(differences),
        shared_groups=len(shared),
        compared_chain_id=compared_chain_id,
        insufficient=False,
    )


def hypothetical_fits(
    alarm_id: str, rival_statistics: ChannelStatistics
) -> tuple[GroupFit, ...]:
    """``Fit_g(x, C')``: how well ``x`` would fit a competing chain.

    ``rival_statistics`` must have been accumulated with ``x`` compared against
    the rival's members.
    """
    from groups.fit import group_fits

    return tuple(group_fits(alarm_id, rival_statistics))
