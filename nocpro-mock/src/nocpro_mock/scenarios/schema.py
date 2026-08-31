"""Scenario definition loading and validation.

Two scenario field sets appear in the docs and are reconciled here:

- ``docs/docs/10-scenarios-and-fixtures.md`` states a minimum of ``scenario_id``,
  ``scenario_version``, ``seed``, ``base_fixture``, ``mutations`` and
  ``expected_contract_assertions``.
- The shipped fixtures in ``docs/examples/synthetic/`` carry ``scenario_id``,
  ``source_kind``, ``seed`` plus a payload block and ``expected_capability`` /
  ``rules`` / ``validation``.

The shipped fixtures are treated as authoritative for their own payload shape;
the docs-10 governance fields are accepted as optional. Only ``scenario_id``,
``seed`` and ``source_kind`` are required, because those three are what
determinism and provenance stamping actually depend on.

Naming rule (docs 07): synthetic identifiers must be obviously synthetic, so a
real-looking identifier such as ``DEHL01`` is rejected rather than stamped
``SYNTHETIC_TEST``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..contract import SourceKind

#: Token marking an identifier as synthetic, as either a prefix (``SYN-CORE-01``)
#: or an infix (``SRLG-SYN-001``).
SYNTHETIC_TOKEN = "SYN"


class ScenarioError(ValueError):
    """Raised when a scenario definition is unusable. Never repaired silently."""


@dataclass(frozen=True)
class TopologySourceDefinition:
    """Exact identity of the topology source modelled by one scenario."""

    source_id: str
    source_version: str


def is_synthetic_identifier(identifier: str) -> bool:
    """True when ``identifier`` carries an explicit ``SYN`` token."""
    return SYNTHETIC_TOKEN in identifier.upper().split("-")


def require_synthetic_identifiers(identifiers: list[str], *, context: str) -> None:
    offenders = sorted({i for i in identifiers if not is_synthetic_identifier(i)})
    if offenders:
        raise ScenarioError(
            f"{context}: identifiers must be obviously synthetic (docs 07); "
            f"offending: {offenders}"
        )


@dataclass(frozen=True)
class ScenarioDefinition:
    """One scenario definition, as declared on disk."""

    scenario_id: str
    seed: int
    source_kind: SourceKind
    raw: dict[str, Any] = field(default_factory=dict)
    scenario_version: str | None = None
    base_fixture: str | None = None
    mutations: tuple[str, ...] = ()
    expected_contract_assertions: tuple[Any, ...] = ()
    topology_source: TopologySourceDefinition | None = None

    def block(self, name: str) -> Any:
        return self.raw.get(name)

    def require_block(self, name: str) -> Any:
        value = self.raw.get(name)
        if value is None:
            raise ScenarioError(
                f"scenario {self.scenario_id!r} is missing required block {name!r}"
            )
        return value

    @property
    def expected_capability(self) -> dict[str, Any]:
        return self.raw.get("expected_capability") or {}

    @property
    def rules(self) -> dict[str, Any]:
        return self.raw.get("rules") or {}

    @property
    def validation(self) -> dict[str, Any]:
        return self.raw.get("validation") or {}


def parse_scenario(data: dict[str, Any]) -> ScenarioDefinition:
    if not isinstance(data, dict):
        raise ScenarioError("scenario definition must be a mapping")

    missing = [k for k in ("scenario_id", "seed", "source_kind") if k not in data]
    if missing:
        raise ScenarioError(f"scenario definition missing required key(s): {missing}")

    raw_kind = str(data["source_kind"])
    try:
        source_kind = SourceKind(raw_kind)
    except ValueError as exc:
        raise ScenarioError(f"unknown source_kind {raw_kind!r}") from exc

    # A scenario file describes generated data; declaring it real would let
    # synthetic input reach validation (ADR-0010).
    if source_kind not in (SourceKind.SYNTHETIC_TEST, SourceKind.BACKFILL):
        raise ScenarioError(
            f"scenario {data['scenario_id']!r} declares source_kind={raw_kind}; "
            "scenarios may only be SYNTHETIC_TEST or BACKFILL (ADR-0010)"
        )

    seed = data["seed"]
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ScenarioError(f"scenario seed must be an integer, got {seed!r}")

    mutations = data.get("mutations") or ()
    assertions = data.get("expected_contract_assertions") or ()

    topology_keys = ("topology", "paths", "failure_domain", "failure_domains")
    has_topology_capability = any(key in data for key in topology_keys)
    topology_source: TopologySourceDefinition | None = None
    if has_topology_capability:
        raw_source = data.get("topology_source")
        if not isinstance(raw_source, dict):
            raise ScenarioError(
                "topology-derived scenario requires topology_source object"
            )
        source_id = raw_source.get("source_id")
        source_version = raw_source.get("source_version")
        if not isinstance(source_id, str) or not source_id.strip():
            raise ScenarioError(
                "topology_source.source_id must be a non-blank string"
            )
        if not isinstance(source_version, str) or not source_version.strip():
            raise ScenarioError(
                "topology_source.source_version must be a non-blank string"
            )
        topology_source = TopologySourceDefinition(
            source_id=source_id,
            source_version=source_version,
        )

    return ScenarioDefinition(
        scenario_id=str(data["scenario_id"]),
        seed=seed,
        source_kind=source_kind,
        raw=data,
        scenario_version=(
            str(data["scenario_version"]) if data.get("scenario_version") else None
        ),
        base_fixture=(str(data["base_fixture"]) if data.get("base_fixture") else None),
        mutations=tuple(str(m) for m in mutations),
        expected_contract_assertions=tuple(assertions),
        topology_source=topology_source,
    )


def load_scenario(path: str | Path) -> ScenarioDefinition:
    """Load one scenario definition from YAML."""
    target = Path(path)
    try:
        data = yaml.safe_load(target.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ScenarioError(f"{target}: invalid YAML: {exc}") from exc
    if data is None:
        raise ScenarioError(f"{target}: empty scenario file")
    return parse_scenario(data)


def load_scenarios(directory: str | Path) -> list[ScenarioDefinition]:
    """Load every scenario in ``directory``, sorted by filename for determinism."""
    base = Path(directory)
    if not base.is_dir():
        raise ScenarioError(f"scenario directory not found: {base}")
    return [load_scenario(p) for p in sorted(base.glob("*.yaml"))]
