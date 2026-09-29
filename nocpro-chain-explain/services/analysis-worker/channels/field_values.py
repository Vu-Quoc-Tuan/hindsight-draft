"""Shared normalization for string-valued evidence fields."""

from __future__ import annotations

import json

from libs.contracts import IngestedAlarm


def _usable_string(value: object) -> str | None:
    if value is None or (
        isinstance(value, (list, tuple, dict, set, frozenset)) and not value
    ):
        return None

    text = str(value).strip()
    if not text or text.casefold() == "n/a":
        return None

    if text.startswith(("[", "{")):
        try:
            decoded = json.loads(text)
        except (TypeError, ValueError):
            pass
        else:
            if isinstance(decoded, (list, dict)) and not decoded:
                return None

    return text


def read_alarm_string_field(alarm: IngestedAlarm, field_name: str) -> str | None:
    """Read a canonical field or raw fallback, treating source placeholders as missing.

    Empty serialized JSON collections (for example ``"[]"``) and ``N/A`` are
    common export placeholders. They cannot support equality or define a burst
    context because matching placeholders does not establish a shared entity.
    """
    canonical = _usable_string(getattr(alarm, field_name, None))
    if canonical is not None:
        return canonical

    raw = getattr(alarm, "raw", None)
    if not isinstance(raw, dict):
        return None
    return _usable_string(raw.get(field_name))
