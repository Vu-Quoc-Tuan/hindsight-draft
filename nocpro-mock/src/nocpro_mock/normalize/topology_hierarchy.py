"""Display-only topology hierarchy helpers.

The functions in this module provide deterministic *visual ordering* for the
topology navigation tree.  They are not dependency direction, routing truth,
active-path truth, or causal/RCA evidence.  In particular, topology classes
and a source-relation arrow MUST NOT be promoted into P2 inference inputs.

P2 promotion requires its separate authoritative business semantics,
alarm-resource mapping, and versioned provenance/configuration contract.
"""

from __future__ import annotations

IP_DISPLAY_LEVELS: dict[str, int] = {
    "CORE": 0,
    "IP_CORE": 0,
    "BACKBONE": 0,
    "AGG_DISTRICT": 1,
    "AGG": 1,
    "METRO": 1,
    "SITE_ROUTER": 2,
    "ACCESS": 2,
    "INTERNAL_SW_LAYER": 2,
    "CLIENT": 3,
}

IT_DISPLAY_LEVELS: dict[str, int] = {
    "SERVICE": 0,
    "MODULE": 1,
    "INSTANCE": 2,
    "DATABASE": 3,
    "STORAGE": 3,
}


def ip_display_level(network_class_name: str | None) -> int:
    """Return a display sorting level; it carries no upstream/downstream meaning."""
    if not network_class_name:
        return 2
    upper = network_class_name.strip().upper()
    for key, rank in IP_DISPLAY_LEVELS.items():
        if key in upper:
            return rank
    return 2


def it_display_level(resource_type: str | None) -> int:
    """Return a display sorting level; it carries no dependency semantics."""
    if not resource_type:
        return 2
    return IT_DISPLAY_LEVELS.get(resource_type.strip().upper(), 2)
