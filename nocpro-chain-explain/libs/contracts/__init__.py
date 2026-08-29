"""Contract ingestion for the analysis core (Direct Snapshot Adapter)."""

from .loader import (
    SUPPORTED_MAJOR_VERSION,
    ContractIngestError,
    IngestedAlarm,
    IngestedChain,
    IngestedPackage,
    IngestedSnapshot,
    load_package,
    load_package_file,
    load_validated_package,
)

__all__ = [
    "SUPPORTED_MAJOR_VERSION",
    "ContractIngestError",
    "IngestedAlarm",
    "IngestedChain",
    "IngestedPackage",
    "IngestedSnapshot",
    "load_package",
    "load_package_file",
    "load_validated_package",
]
