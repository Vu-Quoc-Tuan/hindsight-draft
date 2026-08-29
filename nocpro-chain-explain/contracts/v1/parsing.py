"""Strict JSON-object parser for the canonical Input Contract v1.

The analysis loader intentionally exposes a compact runtime view.  Transport
adapters use this parser first so that relaxed runtime loading can never bypass
the complete versioned contract or its fail-closed enum vocabulary.
"""

from __future__ import annotations

import dataclasses
import types
from enum import Enum
from typing import Any, get_args, get_origin, get_type_hints

from .models import MockSnapshotPackage
from .validation import ContractViolation, validate_package


def _violation(path: str, message: str) -> ContractViolation:
    return ContractViolation(f"{path}: {message}")


def _parse(value: Any, expected: Any, path: str) -> Any:
    if expected is Any:
        return value

    origin = get_origin(expected)
    args = get_args(expected)
    if origin in (types.UnionType, getattr(__import__("typing"), "Union")):
        if value is None and type(None) in args:
            return None
        failures: list[str] = []
        for option in args:
            if option is type(None):
                continue
            try:
                return _parse(value, option, path)
            except ContractViolation as exc:
                failures.append(str(exc))
        raise _violation(path, "value does not match any allowed type")

    if dataclasses.is_dataclass(expected):
        if not isinstance(value, dict):
            raise _violation(path, "expected an object")
        fields = {field.name: field for field in dataclasses.fields(expected)}
        unknown = sorted(set(value) - set(fields))
        if unknown:
            raise _violation(path, f"unexpected field(s): {', '.join(unknown)}")
        hints = get_type_hints(expected)
        parsed: dict[str, Any] = {}
        for name, field in fields.items():
            if name in value:
                parsed[name] = _parse(value[name], hints[name], f"{path}.{name}")
            elif field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING:
                raise _violation(path, f"missing required field {name!r}")
        try:
            return expected(**parsed)
        except (TypeError, ValueError) as exc:
            raise _violation(path, str(exc)) from exc

    if isinstance(expected, type) and issubclass(expected, Enum):
        try:
            return expected(value)
        except (TypeError, ValueError) as exc:
            raise _violation(path, f"invalid {expected.__name__} value {value!r}") from exc

    if origin in (tuple, list):
        if not isinstance(value, list):
            raise _violation(path, "expected an array")
        item_type = args[0] if args else Any
        converted = [_parse(item, item_type, f"{path}[{index}]") for index, item in enumerate(value)]
        return tuple(converted) if origin is tuple else converted

    if origin is dict:
        if not isinstance(value, dict):
            raise _violation(path, "expected an object")
        key_type, value_type = args or (Any, Any)
        return {
            _parse(key, key_type, f"{path}.<key>"): _parse(item, value_type, f"{path}.{key}")
            for key, item in value.items()
        }

    if expected is float and isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if expected is int and isinstance(value, int) and not isinstance(value, bool):
        return value
    if expected is bool and isinstance(value, bool):
        return value
    if expected is str and isinstance(value, str):
        return value
    if isinstance(expected, type) and isinstance(value, expected):
        return value
    raise _violation(path, f"expected {getattr(expected, '__name__', expected)!s}")


def parse_package(payload: dict[str, Any]) -> MockSnapshotPackage:
    """Parse raw JSON data and enforce every Input Contract v1 invariant."""
    package = _parse(payload, MockSnapshotPackage, "package")
    validate_package(package).raise_if_failed()
    return package
