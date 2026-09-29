"""Pre-registered channel applicability policy for offline Audit diagnostics."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from channels.base import EvidenceState

from .contracts import (
    DiagnosticReason,
    InvocationStatus,
    ReasonOrigin,
    ScopeDecision,
    ScopeState,
)


class ScopePolicyError(ValueError):
    """Invalid or ambiguous frozen applicability policy."""


class ScopeEvaluatorInconsistency(ValueError):
    """A frozen scope rule contradicts an available canonical result."""


@dataclass(frozen=True)
class ScopeRule:
    rule_id: str
    predicate: str
    metadata_key: str | None = None
    equals: Any = None


@dataclass(frozen=True)
class ChannelScopeDefinition:
    channel_id: str | None
    channel_id_prefix: str | None
    execution_binding: str
    scope_rule_id: str
    required_scope_metadata: tuple[str, ...]
    not_applicable_rule_ids: tuple[str, ...]
    missing_input_policy: str

    def matches(self, channel_id: str) -> bool:
        if self.channel_id is not None:
            return channel_id == self.channel_id
        assert self.channel_id_prefix is not None
        return channel_id.startswith(self.channel_id_prefix)


@dataclass(frozen=True)
class ScopePolicy:
    policy_id: str
    policy_version: str
    approval_status: str
    rules: Mapping[str, ScopeRule]
    channels: tuple[ChannelScopeDefinition, ...]
    capability_catalog: Mapping[str, Mapping[str, str]]
    digest: str

    def definition_for(self, channel_id: str) -> ChannelScopeDefinition | None:
        exact = [item for item in self.channels if item.channel_id == channel_id]
        if exact:
            return exact[0]
        matches = [item for item in self.channels if item.matches(channel_id)]
        if len(matches) > 1:
            raise ScopePolicyError(
                f"channel {channel_id!r} matches more than one scope definition"
            )
        return matches[0] if matches else None


def load_scope_policy(path: str | Path) -> ScopePolicy:
    """Load a strict YAML registry; no score/evidence fields appear in its rules."""
    target = Path(path)
    try:
        raw_bytes = target.read_bytes()
        document = yaml.safe_load(raw_bytes)
    except OSError as exc:
        raise ScopePolicyError(f"cannot read scope policy {target}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ScopePolicyError(f"invalid scope policy YAML {target}: {exc}") from exc
    if not isinstance(document, dict):
        raise ScopePolicyError("scope policy must be a mapping")
    if document.get("schema_version") != "audit-scope-policy-v1":
        raise ScopePolicyError("unsupported scope policy schema_version")
    policy_id = _required_string(document, "policy_id", "scope policy")
    policy_version = _required_string(document, "policy_version", "scope policy")
    approval_status = _required_string(document, "approval_status", "scope policy")

    raw_rules = document.get("scope_rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        raise ScopePolicyError("scope_rules must be a non-empty list")
    rules: dict[str, ScopeRule] = {}
    for raw_rule in raw_rules:
        if not isinstance(raw_rule, dict):
            raise ScopePolicyError("each scope rule must be a mapping")
        rule_id = _required_string(raw_rule, "rule_id", "scope rule")
        predicate = _required_string(raw_rule, "predicate", f"scope rule {rule_id}")
        if rule_id in rules:
            raise ScopePolicyError(f"duplicate scope rule {rule_id!r}")
        if predicate not in {"every_distinct_pair", "pair_metadata_equals"}:
            raise ScopePolicyError(f"unsupported scope predicate {predicate!r}")
        metadata_key = raw_rule.get("metadata_key")
        if predicate == "pair_metadata_equals" and not isinstance(metadata_key, str):
            raise ScopePolicyError(
                f"scope rule {rule_id!r}: pair_metadata_equals requires metadata_key"
            )
        rules[rule_id] = ScopeRule(
            rule_id=rule_id,
            predicate=predicate,
            metadata_key=metadata_key,
            equals=raw_rule.get("equals"),
        )

    raw_channels = document.get("channels")
    if not isinstance(raw_channels, list) or not raw_channels:
        raise ScopePolicyError("channels must be a non-empty list")
    channels: list[ChannelScopeDefinition] = []
    matchers: set[tuple[str, str]] = set()
    for raw_channel in raw_channels:
        if not isinstance(raw_channel, dict):
            raise ScopePolicyError("each channel scope entry must be a mapping")
        has_exact = "channel_id" in raw_channel
        has_prefix = "channel_id_prefix" in raw_channel
        channel_id = raw_channel.get("channel_id")
        channel_prefix = raw_channel.get("channel_id_prefix")
        if has_exact == has_prefix:
            raise ScopePolicyError(
                "each channel entry requires exactly one channel_id or channel_id_prefix"
            )
        matcher_value = channel_id if has_exact else channel_prefix
        if not isinstance(matcher_value, str) or not matcher_value.strip():
            raise ScopePolicyError("channel ID and prefix matchers must be non-empty strings")
        if matcher_value != matcher_value.strip():
            raise ScopePolicyError("channel ID and prefix matchers cannot contain surrounding whitespace")
        matcher = ("exact", channel_id) if isinstance(channel_id, str) else ("prefix", channel_prefix)
        if matcher in matchers:
            raise ScopePolicyError(f"duplicate channel scope matcher {matcher!r}")
        matchers.add(matcher)
        rule_id = _required_string(raw_channel, "scope_rule_id", "channel scope entry")
        if rule_id not in rules:
            raise ScopePolicyError(f"unknown scope rule {rule_id!r}")
        required = raw_channel.get("required_scope_metadata", [])
        na_rule_ids = raw_channel.get("not_applicable_rule_ids", [])
        if not isinstance(required, list) or any(not isinstance(x, str) or not x.strip() for x in required):
            raise ScopePolicyError("required_scope_metadata must be a list of strings")
        if len(required) != len(set(required)):
            raise ScopePolicyError("required_scope_metadata cannot contain duplicates")
        if not isinstance(na_rule_ids, list) or any(not isinstance(x, str) or not x.strip() for x in na_rule_ids):
            raise ScopePolicyError("not_applicable_rule_ids must be a list of strings")
        if len(na_rule_ids) != len(set(na_rule_ids)):
            raise ScopePolicyError("not_applicable_rule_ids cannot contain duplicates")
        if any(rule not in rules for rule in na_rule_ids):
            raise ScopePolicyError(f"channel references an unknown NOT_APPLICABLE rule")
        for rule in (rules[rule_id], *(rules[x] for x in na_rule_ids)):
            if rule.predicate == "pair_metadata_equals" and rule.metadata_key not in required:
                raise ScopePolicyError(
                    f"channel {channel_id or channel_prefix!r} must predeclare metadata "
                    f"{rule.metadata_key!r} required by rule {rule.rule_id!r}"
                )
        channels.append(
            ChannelScopeDefinition(
                channel_id=channel_id if isinstance(channel_id, str) else None,
                channel_id_prefix=channel_prefix if isinstance(channel_prefix, str) else None,
                execution_binding=_required_string(raw_channel, "execution_binding", "channel scope entry"),
                scope_rule_id=rule_id,
                required_scope_metadata=tuple(required),
                not_applicable_rule_ids=tuple(na_rule_ids),
                missing_input_policy=_required_string(raw_channel, "missing_input_policy", "channel scope entry"),
            )
        )

    prefixes = [item.channel_id_prefix for item in channels if item.channel_id_prefix is not None]
    for index, left in enumerate(prefixes):
        for right in prefixes[index + 1:]:
            if left.startswith(right) or right.startswith(left):
                raise ScopePolicyError(f"overlapping dynamic channel prefixes {left!r} and {right!r}")

    catalog = document.get("capability_catalog", {})
    if not isinstance(catalog, dict) or any(
        not isinstance(key, str) or not isinstance(value, dict)
        for key, value in catalog.items()
    ):
        raise ScopePolicyError("capability_catalog must map IDs to metadata objects")
    return ScopePolicy(
        policy_id=policy_id,
        policy_version=policy_version,
        approval_status=approval_status,
        rules=rules,
        channels=tuple(channels),
        capability_catalog=catalog,
        digest=_sha256(raw_bytes),
    )


def classify_scope(
    pair: tuple[str, str],
    channel_id: str,
    policy: ScopePolicy,
    *,
    invocation: InvocationStatus,
    evidence_state=None,
    pair_scope_metadata: Mapping[str, Any] | None = None,
) -> ScopeDecision:
    """Classify a pair using only pre-registered scope metadata.

    Scores, channel states and Audit results are intentionally unavailable to
    the predicate evaluator. Missing/conflicting metadata stays UNKNOWN.
    """
    definition = policy.definition_for(channel_id)
    if definition is None:
        reason = DiagnosticReason(
            code="SCOPE_RULE_UNDEFINED",
            origin=ReasonOrigin.SCOPE,
            detail=f"No pre-registered scope rule matches channel {channel_id}.",
        )
        return ScopeDecision(
            scope=ScopeState.UNKNOWN_APPLICABILITY,
            rule_ids=(),
            invocation=invocation,
            evidence_state=evidence_state,
            primary_reason=reason,
        )

    metadata = pair_scope_metadata or {}
    required_rule_ids = (definition.scope_rule_id, *definition.not_applicable_rule_ids)
    rules = [policy.rules[item] for item in required_rule_ids]
    for metadata_key in definition.required_scope_metadata:
        if metadata_key not in metadata or metadata[metadata_key] is None:
            reason = DiagnosticReason(
                code="SCOPE_METADATA_MISSING",
                origin=ReasonOrigin.SCOPE,
                detail=f"Required pre-registered scope metadata {metadata_key!r} is missing.",
            )
            return ScopeDecision(
                scope=ScopeState.UNKNOWN_APPLICABILITY,
                rule_ids=required_rule_ids,
                invocation=invocation,
                evidence_state=evidence_state,
                primary_reason=reason,
            )
        value = metadata[metadata_key]
        if isinstance(value, (list, tuple, set, frozenset)) and len({
            json.dumps(item, sort_keys=True, separators=(",", ":"), default=str)
            for item in value
        }) > 1:
            reason = DiagnosticReason(
                code="SCOPE_METADATA_CONFLICT",
                origin=ReasonOrigin.SCOPE,
                detail=f"Scope metadata {metadata_key!r} has conflicting values.",
            )
            return ScopeDecision(
                scope=ScopeState.UNKNOWN_APPLICABILITY,
                rule_ids=required_rule_ids,
                invocation=invocation,
                evidence_state=evidence_state,
                primary_reason=reason,
            )

    # Positive proof that a declared NOT_APPLICABLE predicate matches wins;
    # absent or ambiguous metadata never creates such proof.
    for rule_id in definition.not_applicable_rule_ids:
        rule = policy.rules[rule_id]
        if _rule_matches(rule, metadata):
            if evidence_state in {EvidenceState.SUPPORT, EvidenceState.NEUTRAL}:
                raise ScopeEvaluatorInconsistency(
                    f"{channel_id} produced available evidence outside registered scope for {pair}"
                )
            return ScopeDecision(
                scope=ScopeState.NOT_APPLICABLE,
                rule_ids=required_rule_ids,
                invocation=invocation,
                evidence_state=evidence_state,
            )

    # The v1 population rule covers every distinct pair. A future positive
    # applicability predicate must be evaluated explicitly, not guessed.
    scope_rule = policy.rules[definition.scope_rule_id]
    if scope_rule.predicate == "every_distinct_pair":
        state = ScopeState.APPLICABLE
    elif scope_rule.predicate == "pair_metadata_equals":
        value = metadata.get(scope_rule.metadata_key)
        state = ScopeState.APPLICABLE if value == scope_rule.equals else ScopeState.UNKNOWN_APPLICABILITY
    else:  # Loader rejects this, retained as a fail-closed guard.
        state = ScopeState.UNKNOWN_APPLICABILITY

    if state is ScopeState.UNKNOWN_APPLICABILITY:
        reason = DiagnosticReason(
            code="SCOPE_METADATA_MISSING",
            origin=ReasonOrigin.SCOPE,
            detail=f"Scope predicate {scope_rule.rule_id!r} cannot be resolved.",
        )
        return ScopeDecision(
            scope=state,
            rule_ids=required_rule_ids,
            invocation=invocation,
            evidence_state=evidence_state,
            primary_reason=reason,
        )
    return ScopeDecision(
        scope=state,
        rule_ids=required_rule_ids,
        invocation=invocation,
        evidence_state=evidence_state,
    )


def _rule_matches(rule: ScopeRule, metadata: Mapping[str, Any]) -> bool:
    if rule.predicate == "every_distinct_pair":
        return False
    if rule.predicate == "pair_metadata_equals":
        return metadata.get(rule.metadata_key) == rule.equals
    return False


def _required_string(mapping: Mapping[str, Any], key: str, context: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ScopePolicyError(f"{context}: {key} must be a non-empty string")
    return value.strip()


def _sha256(value: bytes) -> str:
    import hashlib

    return hashlib.sha256(value).hexdigest()
