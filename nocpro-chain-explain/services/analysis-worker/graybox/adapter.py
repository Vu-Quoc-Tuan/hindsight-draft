"""Gray-box NocPro Metadata Adapter (MVP item 1, §2, ADR-0008/0029).

Ingests what NocPro actually said about a chain: rules, merge strategy,
connector/extender counts, Attribute configuration, aggregate characteristics and
exact ``M_pair`` when upstream supplies it. It does **not** require simiDict,
``A_ij`` or ΔQ, and never fabricates them.

Type discipline (ADR-0008). Everything here stays ``SYSTEM_FACT``:
- raw scores are never normalized into an Evidence-channel ``s_k``;
- aggregate ``pair_count`` never synthesizes exact pair edges;
- ``M_pair`` is not an Attribute config and vice versa;
- NocPro ``TimeWindow``/``HistorySimilarity``/``TopologySimilarity`` are never
  collapsed into the module's ``T_burst``/``T_delay``, ``H`` or ``Dep_*``.

ADR-0029 requires this to be a real adapter over the contract, not hard-coded
metadata, so a demo that ingests nothing renders an explicitly empty System Fact
box rather than inventing content.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from libs.contracts.loader import IngestedPackage

#: Coverage scope values (contract v1). Anything else resolves to UNKNOWN.
_COVERAGE_SCOPES = {"FULL_PAIR_SPACE", "BOUNDED_COMPARISON", "UNKNOWN"}
#: Pair status values. A missing record defaults to UNKNOWN, never NEUTRAL.
_PAIR_STATUSES = {"EVALUATED", "NOT_EVALUATED", "UNKNOWN"}
_SYSTEM_SEMANTICS = {"SUPPORT", "NEUTRAL", "VETO", "UNKNOWN"}

#: NocPro Attribute type ids, from the Attribute/Louvain report.
ATTRIBUTE_TYPE_NAMES = {
    1: "Expression",
    2: "Algorithm",
    3: "TimeWindow",
    4: "HistorySimilarity",
    5: "TopologySimilarity",
}


@dataclass(frozen=True)
class RuleAnnotation:
    """``M_chain_rule``: rule / connector-extender / merge.

    Connector and extender labels are replayed verbatim. Their exact semantics
    are not inferred, because the source has not confirmed them (§2).
    """

    rule_name: str
    member_count: int
    connector_count: int | None = None
    extender_count: int | None = None
    merge_strategy: str | None = None

    @property
    def connector_ratio(self) -> float | None:
        if self.connector_count is None or not self.member_count:
            return None
        return self.connector_count / self.member_count


@dataclass(frozen=True)
class ChainCharacteristic:
    """``M_chain_characteristic``: aggregate count, never expanded to pairs."""

    name: str
    pair_count: int
    coverage_scope: str
    value: str | None = None
    threshold_seconds: int | None = None

    @property
    def covers_full_pair_space(self) -> bool:
        """True only when upstream proved full coverage for this characteristic."""
        return self.coverage_scope == "FULL_PAIR_SPACE"


@dataclass(frozen=True)
class AttributeConfiguration:
    """``M_attribute_config``: type/content/algorithm/filter/weight only."""

    attribute_type: int
    attribute_ref: str | None = None
    content: str | None = None
    algorithm_type: str | None = None
    filter_name: str | None = None
    weight: float | None = None

    @property
    def type_name(self) -> str:
        return ATTRIBUTE_TYPE_NAMES.get(self.attribute_type, "Unknown")


@dataclass(frozen=True)
class SystemPairFact:
    """``M_pair``: exact per-pair raw score/veto/status for one Attribute."""

    alarm_id_a: str
    alarm_id_b: str
    system_pair_status: str
    attribute_ref: str | None = None
    raw_score: float | None = None
    system_semantic: str | None = None

    @property
    def key(self) -> tuple[str, str]:
        """Undirected pair identity."""
        return tuple(sorted((self.alarm_id_a, self.alarm_id_b)))  # type: ignore[return-value]

    @property
    def is_veto(self) -> bool:
        return self.system_semantic == "VETO"

    @property
    def is_evaluated(self) -> bool:
        return self.system_pair_status == "EVALUATED"


@dataclass(frozen=True)
class PairCoverageBatch:
    """Batch-level coverage for a set of ``M_pair`` records.

    Needed to interpret a *missing* pair: under ``BOUNDED_COMPARISON`` absence
    means "not compared", which is not "compared and unrelated".
    """

    batch_id: str
    coverage_scope: str
    attribute_ref: str | None = None
    pair_count: int | None = None
    max_compare_per_alarm: int | None = None


@dataclass
class GrayBoxMetadata:
    """All system-provided metadata for one chain. Always ``SYSTEM_FACT``."""

    chain_id: str
    rules: tuple[RuleAnnotation, ...] = ()
    characteristics: tuple[ChainCharacteristic, ...] = ()
    attribute_configs: tuple[AttributeConfiguration, ...] = ()
    pair_facts: tuple[SystemPairFact, ...] = ()
    coverage_batches: tuple[PairCoverageBatch, ...] = ()
    #: Capabilities upstream declared unavailable, e.g. EXACT_PAIR_METADATA.
    unavailable_capabilities: tuple[str, ...] = ()
    _pair_index: dict[tuple[str, str], SystemPairFact] = field(
        default_factory=dict, repr=False
    )

    @property
    def available(self) -> bool:
        """Whether any gray-box metadata was ingested at all.

        False means Black-box mode for this chain: every feature still runs,
        minus the system evidence layer (graceful degradation, §2).
        """
        return bool(
            self.rules
            or self.characteristics
            or self.attribute_configs
            or self.pair_facts
        )

    @property
    def merge_strategy(self) -> str | None:
        for rule in self.rules:
            if rule.merge_strategy:
                return rule.merge_strategy
        return None

    def rule(self, rule_name: str) -> RuleAnnotation | None:
        return next((r for r in self.rules if r.rule_name == rule_name), None)

    def pair_fact(self, alarm_a: str, alarm_b: str) -> SystemPairFact | None:
        """Exact pair metadata, or ``None`` when no record exists."""
        return self._pair_index.get(tuple(sorted((alarm_a, alarm_b))))

    def pair_status(self, alarm_a: str, alarm_b: str) -> str:
        """Resolve pair status, defaulting to ``UNKNOWN``.

        A missing record is ``UNKNOWN`` and therefore unavailable downstream. It
        is never ``NEUTRAL``: that would assert the system evaluated the pair and
        found nothing (ADR-0002, ADR-0008).
        """
        fact = self.pair_fact(alarm_a, alarm_b)
        return fact.system_pair_status if fact else "UNKNOWN"

    def characteristics_named(self, name: str) -> tuple[ChainCharacteristic, ...]:
        return tuple(c for c in self.characteristics if c.name == name)

    def coverage_scope_for(self, attribute_ref: str | None) -> str:
        for batch in self.coverage_batches:
            if batch.attribute_ref == attribute_ref:
                return batch.coverage_scope
        return "UNKNOWN"


def _coverage_scope(raw: Any) -> str:
    """Normalize a coverage scope, failing closed to UNKNOWN."""
    text = str(raw) if raw is not None else "UNKNOWN"
    return text if text in _COVERAGE_SCOPES else "UNKNOWN"


def _pair_status(raw: Any) -> str:
    text = str(raw) if raw is not None else "UNKNOWN"
    return text if text in _PAIR_STATUSES else "UNKNOWN"


def _system_semantic(raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw)
    return text if text in _SYSTEM_SEMANTICS else "UNKNOWN"


def adapt_graybox_metadata(
    package: IngestedPackage, chain_id: str
) -> GrayBoxMetadata:
    """Extract the gray-box metadata for one chain from an ingested package."""
    sm = package.system_metadata

    rules = tuple(
        RuleAnnotation(
            rule_name=str(entry["rule_name"]),
            member_count=int(entry.get("member_count", 0)),
            connector_count=(
                int(entry["connector_count"])
                if entry.get("connector_count") is not None
                else None
            ),
            extender_count=(
                int(entry["extender_count"])
                if entry.get("extender_count") is not None
                else None
            ),
            merge_strategy=entry.get("merge_strategy"),
        )
        for entry in (sm.get("chain_rules") or ())
        if entry.get("chain_id") == chain_id and entry.get("rule_name")
    )

    characteristics = tuple(
        ChainCharacteristic(
            name=str(entry["name"]),
            pair_count=int(entry.get("pair_count", 0)),
            coverage_scope=_coverage_scope(entry.get("coverage_scope")),
            value=entry.get("value"),
            threshold_seconds=(
                int(entry["threshold_seconds"])
                if entry.get("threshold_seconds") is not None
                else None
            ),
        )
        for entry in (sm.get("chain_characteristics") or ())
        if entry.get("chain_id") == chain_id and entry.get("name")
    )

    # Attribute configs are chain-independent in the contract.
    attribute_configs = tuple(
        AttributeConfiguration(
            attribute_type=int(entry.get("attribute_type", 0)),
            attribute_ref=entry.get("attribute_ref"),
            content=entry.get("content"),
            algorithm_type=entry.get("algorithm_type"),
            filter_name=entry.get("filter_name"),
            weight=(
                float(entry["weight"]) if entry.get("weight") is not None else None
            ),
        )
        for entry in (sm.get("attribute_configs") or ())
    )

    pair_facts = tuple(
        SystemPairFact(
            alarm_id_a=str(entry["alarm_id_a"]),
            alarm_id_b=str(entry["alarm_id_b"]),
            system_pair_status=_pair_status(entry.get("system_pair_status")),
            attribute_ref=entry.get("attribute_ref"),
            raw_score=(
                float(entry["raw_score"]) if entry.get("raw_score") is not None else None
            ),
            system_semantic=_system_semantic(entry.get("system_semantic")),
        )
        for entry in (sm.get("pair_metadata") or ())
        if entry.get("chain_id") == chain_id
        and entry.get("alarm_id_a")
        and entry.get("alarm_id_b")
    )

    coverage_batches = tuple(
        PairCoverageBatch(
            batch_id=str(entry.get("batch_id", "")),
            coverage_scope=_coverage_scope(entry.get("coverage_scope")),
            attribute_ref=entry.get("attribute_ref"),
            pair_count=(
                int(entry["pair_count"]) if entry.get("pair_count") is not None else None
            ),
            max_compare_per_alarm=(
                int(entry["max_compare_per_alarm"])
                if entry.get("max_compare_per_alarm") is not None
                else None
            ),
        )
        for entry in (sm.get("pair_metadata_batches") or ())
        if entry.get("chain_id") in (None, chain_id)
    )

    metadata = GrayBoxMetadata(
        chain_id=chain_id,
        rules=rules,
        characteristics=characteristics,
        attribute_configs=attribute_configs,
        pair_facts=pair_facts,
        coverage_batches=coverage_batches,
        unavailable_capabilities=package.unavailable_capabilities,
    )
    metadata._pair_index = {fact.key: fact for fact in pair_facts}
    return metadata
