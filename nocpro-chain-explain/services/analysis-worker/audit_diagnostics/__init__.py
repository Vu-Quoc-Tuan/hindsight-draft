"""Offline Audit diagnostics; importing this package performs no analysis."""

from __future__ import annotations

from typing import Any


def prepare(*args: Any, **kwargs: Any):
    """Freeze a diagnostic manifest without evaluating channels or scoring."""
    from .runner import prepare as prepare_run

    return prepare_run(*args, **kwargs)


def run_manifest(*args: Any, **kwargs: Any):
    """Execute a previously frozen diagnostic manifest."""
    from .runner import run_manifest as execute_run

    return execute_run(*args, **kwargs)


__all__ = ["prepare", "run_manifest"]
