"""Canonical Input Contract v1 — deterministic serialization.

Determinism requirement (nocpro-mock docs 07 / ADR-0026): same input + seed +
config must produce byte-equivalent output. Dict key order therefore follows
dataclass field declaration order, and ``None`` values are dropped so optional
fields cannot introduce spurious diffs.
"""

from __future__ import annotations

import dataclasses
import json
from enum import Enum
from typing import Any


def to_jsonable(value: Any) -> Any:
    """Convert contract objects into JSON-safe primitives, dropping ``None``."""
    if isinstance(value, Enum):
        return value.value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        out: dict[str, Any] = {}
        for f in dataclasses.fields(value):
            converted = to_jsonable(getattr(value, f.name))
            if converted is None:
                continue
            out[f.name] = converted
        return out
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    return value


def package_to_dict(package: Any) -> dict[str, Any]:
    return to_jsonable(package)


def package_to_json(package: Any, *, indent: int | None = 2) -> str:
    """Serialize deterministically.

    ``sort_keys`` is intentionally False: declaration order is already
    deterministic and is more readable than alphabetical order.
    """
    return json.dumps(
        package_to_dict(package),
        indent=indent,
        ensure_ascii=False,
        sort_keys=False,
    )
