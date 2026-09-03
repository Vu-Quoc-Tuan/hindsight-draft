"""Observed fixtures. Read-only by policy (ADR-MOCK-0004)."""

from .golden import (
    GOLDEN_CHAIN_ID,
    GOLDEN_FIXTURE_ID,
    GoldenFixture,
    load_golden_fixture,
)
from .operator_feedback import (
    OperatorFeedbackRecord,
    SyntheticOperatorFeedbackFixture,
    load_synthetic_operator_feedback,
)

__all__ = [
    "GOLDEN_CHAIN_ID",
    "GOLDEN_FIXTURE_ID",
    "GoldenFixture",
    "load_golden_fixture",
    "OperatorFeedbackRecord",
    "SyntheticOperatorFeedbackFixture",
    "load_synthetic_operator_feedback",
]
