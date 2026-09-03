"""Extract event-identity-preserving temporal observations from a DAG prefix."""

from __future__ import annotations

from evolution import GlobalEpisodeDag
from history import HistoricalTaxonomy, TaxonomyLevel
from libs.contracts import IngestedPackage

from .model import DelayObservation, DelayRelationKey, _time


def observations_from_lineage_prefix(
    packages: list[IngestedPackage], *, dag: GlobalEpisodeDag, cutoff: str, taxonomy: HistoricalTaxonomy
) -> tuple[DelayObservation, ...]:
    """Only same-chain, before-cutoff event pairs enter the learned corpus."""
    cutoff_time = _time(cutoff)
    by_identity = {
        (package.snapshot.snapshot_id, package.snapshot.snapshot_version): package
        for package in packages if _time(package.snapshot.snapshot_time) < cutoff_time
    }
    nodes = [node for key, node in dag.nodes.items() if (key.snapshot_id, key.snapshot_version) in by_identity and _time(node.snapshot_time) < cutoff_time]
    # Rebuild prefix components from prefix edges; do not use post-cutoff aliases.
    keys = {node.key for node in nodes}
    adjacent = {key: set() for key in keys}
    for edge in dag.edges.values():
        if edge.parent in keys and edge.child in keys:
            adjacent[edge.parent].add(edge.child); adjacent[edge.child].add(edge.parent)
    episode_of = {}
    remaining = set(keys)
    while remaining:
        root = min(remaining); stack = [root]; remaining.remove(root)
        component = []
        while stack:
            key = stack.pop(); component.append(key)
            for peer in sorted(adjacent[key]):
                if peer in remaining: remaining.remove(peer); stack.append(peer)
        episode_id = "episode:" + "|".join(f"{key.snapshot_id}:{key.snapshot_version}:{key.snapshot_chain_id}" for key in sorted(component))
        episode_of.update({key: episode_id for key in component})
    observed: dict[tuple[str, str, str, TaxonomyLevel], DelayObservation] = {}
    for key, episode_id in episode_of.items():
        package = by_identity[(key.snapshot_id, key.snapshot_version)]
        events = []
        for alarm in package.alarms_of(key.snapshot_chain_id):
            tokens = taxonomy.resolve(alarm)
            start = _time(alarm.canonical_start_time) if alarm.canonical_start_time else None
            if tokens is not None and start is not None: events.append((alarm, tokens, start))
        for source, source_tokens, source_time in events:
            for target, target_tokens, target_time in events:
                # Equal timestamps have no defensible direction.  They remain
                # contextual burst evidence, never fabricated bidirectional
                # learned delay signatures.
                if source.alarm_id == target.alarm_id or target_time <= source_time: continue
                for level in (TaxonomyLevel.TYPE, TaxonomyLevel.FAMILY, TaxonomyLevel.CATEGORY):
                    left, right = source_tokens.at(level), target_tokens.at(level)
                    if left is None or right is None: continue
                    item = DelayObservation(
                        episode_id, source.alarm_id, target.alarm_id,
                        DelayRelationKey(level, left, right),
                        (target_time-source_time).total_seconds(),
                        key.snapshot_id, key.snapshot_version, key.snapshot_chain_id,
                    )
                    observed.setdefault((episode_id, source.alarm_id, target.alarm_id, level), item)
    return tuple(sorted(observed.values(), key=lambda item: (item.key, item.episode_id, item.source_alarm_id, item.target_alarm_id)))
