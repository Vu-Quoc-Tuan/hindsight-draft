"""Versioned mock configuration and capability flags.

docs 06/12: quality thresholds live in versioned config, never hardcoded in the
generator. docs 03: a missing threshold yields UNKNOWN rather than a guess.

The YAML shape mirrors ``docs/config/mock_capabilities.example.yaml``. Parsing is
dependency-free so P0 does not require PyYAML for the flat subset used here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_VERSION = "mock-v1"
GENERATOR_VERSION = "nocpro-mock-0.1.0"


@dataclass(frozen=True)
class TopoIPCapabilities:
    """Capabilities a plain adjacency export can and cannot support (docs 06)."""

    adjacency: bool = True
    freshness: bool = True
    directed_dependency: bool = False
    active_path: bool = False
    failure_domain: bool = False


@dataclass(frozen=True)
class Policy:
    """Hard policy switches. Defaults are the safe (fail-closed) values."""

    mutate_golden_fixture_in_place: bool = False
    allow_fuzzy_topology_mapping: bool = False
    synthetic_can_validate: bool = False
    missing_pair_metadata_defaults_to: str = "UNKNOWN"


@dataclass(frozen=True)
class MockConfig:
    config_version: str = DEFAULT_CONFIG_VERSION
    generator_version: str = GENERATOR_VERSION
    alarm_csv_enabled: bool = True
    topo_ip_enabled: bool = True
    topo_ip_capabilities: TopoIPCapabilities = field(default_factory=TopoIPCapabilities)
    topo_it_enabled: bool = False
    topo_it_disabled_reason: str = "archive schema not yet verified"
    synthetic_generators: dict[str, bool] = field(default_factory=dict)
    policy: Policy = field(default_factory=Policy)
    #: Freshness PASS threshold. ``None`` means unknown -> quality_status UNKNOWN.
    topology_freshness_pass_max_age_seconds: int | None = None
    #: Timestamps at or beyond this year are flagged as future outliers.
    future_timestamp_year_threshold: int = 2030

    def synthetic_enabled(self, name: str) -> bool:
        return self.synthetic_generators.get(name, False)

    def assert_policy_safe(self) -> None:
        """Guard the invariants that must never be configured away."""
        if self.policy.allow_fuzzy_topology_mapping:
            raise ValueError(
                "allow_fuzzy_topology_mapping=true is forbidden by ADR-MOCK-0005"
            )
        if self.policy.synthetic_can_validate:
            raise ValueError("synthetic_can_validate=true is forbidden by ADR-0010")
        if self.policy.mutate_golden_fixture_in_place:
            raise ValueError(
                "mutate_golden_fixture_in_place=true is forbidden by ADR-MOCK-0004"
            )
        if self.policy.missing_pair_metadata_defaults_to != "UNKNOWN":
            raise ValueError(
                "missing pair metadata must default to UNKNOWN, not "
                f"{self.policy.missing_pair_metadata_defaults_to!r} (ADR-0002)"
            )


def _coerce_scalar(raw: str) -> Any:
    text = raw.strip().strip('"').strip("'")
    lowered = text.lower()
    if lowered in ("true", "yes"):
        return True
    if lowered in ("false", "no"):
        return False
    if lowered in ("null", "none", ""):
        return None
    try:
        return int(text)
    except ValueError:
        return text


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    """Parse the indented key/value subset used by the capability config.

    Supports nested mappings and scalars only; the capability config needs no
    lists or anchors. Anything richer should adopt PyYAML explicitly rather than
    being silently mis-parsed.
    """
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]

    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        indent = len(line) - len(line.lstrip())
        key, _, rest = line.strip().partition(":")
        key = key.strip()
        rest = rest.strip()

        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1] if stack else root

        if rest == "":
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _coerce_scalar(rest)

    return root


def load_config(path: str | Path | None = None) -> MockConfig:
    """Load configuration, falling back to safe defaults when no file is given."""
    if path is None:
        return MockConfig(synthetic_generators=_default_generators())

    data = _parse_simple_yaml(Path(path).read_text(encoding="utf-8"))
    real = data.get("real_sources", {}) or {}
    topo_ip = real.get("topo_ip", {}) or {}
    caps = topo_ip.get("capabilities", {}) or {}
    topo_it = real.get("topo_it", {}) or {}
    policy_raw = data.get("policy", {}) or {}
    generators_raw = data.get("synthetic_generators", {}) or {}

    generators = {
        name: bool((spec or {}).get("enabled", False))
        for name, spec in generators_raw.items()
        if isinstance(spec, dict)
    }

    config = MockConfig(
        config_version=str(data.get("config_version", DEFAULT_CONFIG_VERSION)),
        alarm_csv_enabled=bool((real.get("alarm_csv", {}) or {}).get("enabled", True)),
        topo_ip_enabled=bool(topo_ip.get("enabled", True)),
        topo_ip_capabilities=TopoIPCapabilities(
            adjacency=bool(caps.get("adjacency", True)),
            freshness=bool(caps.get("freshness", True)),
            directed_dependency=bool(caps.get("directed_dependency", False)),
            active_path=bool(caps.get("active_path", False)),
            failure_domain=bool(caps.get("failure_domain", False)),
        ),
        topo_it_enabled=bool(topo_it.get("enabled", False)),
        topo_it_disabled_reason=str(
            topo_it.get("reason", "archive schema not yet verified")
        ),
        synthetic_generators=generators or _default_generators(),
        policy=Policy(
            mutate_golden_fixture_in_place=bool(
                policy_raw.get("mutate_golden_fixture_in_place", False)
            ),
            allow_fuzzy_topology_mapping=bool(
                policy_raw.get("allow_fuzzy_topology_mapping", False)
            ),
            synthetic_can_validate=bool(policy_raw.get("synthetic_can_validate", False)),
            missing_pair_metadata_defaults_to=str(
                policy_raw.get("missing_pair_metadata_defaults_to", "UNKNOWN")
            ),
        ),
    )
    config.assert_policy_safe()
    return config


def _default_generators() -> dict[str, bool]:
    return {
        "dependency_hierarchy": True,
        "active_path": True,
        "failure_domain": True,
        "operational_context": True,
        "history": True,
        "evolution": True,
        "system_pair_metadata": True,
    }
