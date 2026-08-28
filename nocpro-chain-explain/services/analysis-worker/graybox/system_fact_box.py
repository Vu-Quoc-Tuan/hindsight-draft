"""System Fact box rendering (§2 UI discipline).

The UI separates SYSTEM-PROVIDED EVIDENCE from POST-HOC ANALYSIS. This module
renders the system side only, so post-hoc conclusions can never leak into the
box that claims to state what NocPro said.

Wording discipline: this reports what the system provided. It does not assert why
NocPro grouped anything, and it does not translate connector/extender labels into
semantics the source has not confirmed.
"""

from __future__ import annotations

from dataclasses import dataclass

from .adapter import GrayBoxMetadata


@dataclass(frozen=True)
class SystemFactLine:
    """One display line, with a machine-readable kind for the UI."""

    kind: str
    text: str


def render_system_fact_box(metadata: GrayBoxMetadata) -> list[SystemFactLine]:
    """Render the system-provided evidence box for one chain."""
    if not metadata.available:
        # Black-box mode: state the absence rather than filling the box.
        lines = [
            SystemFactLine(
                kind="MODE",
                text="No system-provided metadata for this chain (Black-box mode).",
            )
        ]
        lines.extend(_unavailable_lines(metadata))
        return lines

    lines: list[SystemFactLine] = []

    for rule in metadata.rules:
        parts = [f"{rule.rule_name}:"]
        if rule.connector_count is not None:
            parts.append(f"{rule.connector_count}/{rule.member_count} connector")
        if rule.extender_count is not None:
            parts.append(f"+ {rule.extender_count} extender")
        lines.append(SystemFactLine(kind="RULE", text=" ".join(parts)))

    if metadata.merge_strategy:
        lines.append(
            SystemFactLine(kind="MERGE", text=f"Merge: {metadata.merge_strategy}")
        )

    for characteristic in metadata.characteristics:
        descriptor = characteristic.name
        if characteristic.value:
            descriptor = f"{descriptor} = {characteristic.value}"
        if characteristic.threshold_seconds is not None:
            descriptor = f"{descriptor} (<{characteristic.threshold_seconds}s)"
        suffix = (
            " [full pair space]"
            if characteristic.covers_full_pair_space
            else " [coverage unknown]"
            if characteristic.coverage_scope == "UNKNOWN"
            else " [bounded comparison]"
        )
        lines.append(
            SystemFactLine(
                kind="CHARACTERISTIC",
                text=f"{characteristic.pair_count} pairs {descriptor}{suffix}",
            )
        )

    for config in metadata.attribute_configs:
        detail = [f"Attribute {config.attribute_type} {config.type_name}"]
        if config.content:
            detail.append(f"content={config.content}")
        if config.weight is not None:
            detail.append(f"weight={config.weight}")
        lines.append(SystemFactLine(kind="ATTRIBUTE_CONFIG", text=" · ".join(detail)))

    if metadata.pair_facts:
        evaluated = sum(1 for f in metadata.pair_facts if f.is_evaluated)
        vetoed = sum(1 for f in metadata.pair_facts if f.is_veto)
        summary = f"Exact pair metadata: {len(metadata.pair_facts)} record(s), {evaluated} evaluated"
        if vetoed:
            summary += f", {vetoed} veto"
        lines.append(SystemFactLine(kind="PAIR_METADATA", text=summary))

    lines.extend(_unavailable_lines(metadata))
    return lines


def _unavailable_lines(metadata: GrayBoxMetadata) -> list[SystemFactLine]:
    """Declare unavailable capabilities explicitly.

    Absence must read as "not provided", never as a negative finding.
    """
    if not metadata.unavailable_capabilities:
        return []
    return [
        SystemFactLine(
            kind="UNAVAILABLE",
            text="Not provided by upstream: "
            + ", ".join(metadata.unavailable_capabilities),
        )
    ]


def render_text(metadata: GrayBoxMetadata) -> str:
    header = "SYSTEM-PROVIDED EVIDENCE"
    body = "\n".join(f"  {line.text}" for line in render_system_fact_box(metadata))
    return f"{header}\n{'-' * len(header)}\n{body}"
