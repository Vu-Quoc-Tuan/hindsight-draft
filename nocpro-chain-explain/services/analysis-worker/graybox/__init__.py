"""Gray-box NocPro metadata adapter and singleton path (MVP)."""

from .adapter import (
    ATTRIBUTE_TYPE_NAMES,
    AttributeConfiguration,
    ChainCharacteristic,
    GrayBoxMetadata,
    PairCoverageBatch,
    RuleAnnotation,
    SystemPairFact,
    adapt_graybox_metadata,
)
from .singleton import (
    PAIR_DEPENDENT_OPERATIONS,
    SINGLETON_SUPPORTED_OPERATIONS,
    MembershipVerdict,
    OperationResult,
    OperationStatus,
    SingletonReport,
    build_singleton_report,
    operation_status,
    singleton_membership_verdict,
)
from .system_fact_box import SystemFactLine, render_system_fact_box, render_text

__all__ = [
    "ATTRIBUTE_TYPE_NAMES",
    "PAIR_DEPENDENT_OPERATIONS",
    "SINGLETON_SUPPORTED_OPERATIONS",
    "AttributeConfiguration",
    "ChainCharacteristic",
    "GrayBoxMetadata",
    "MembershipVerdict",
    "OperationResult",
    "OperationStatus",
    "PairCoverageBatch",
    "RuleAnnotation",
    "SingletonReport",
    "SystemFactLine",
    "SystemPairFact",
    "adapt_graybox_metadata",
    "build_singleton_report",
    "operation_status",
    "render_system_fact_box",
    "render_text",
    "singleton_membership_verdict",
]
