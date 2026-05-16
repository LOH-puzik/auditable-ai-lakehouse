"""Synthetic SWIFT message generator (MT540, MT548) with controlled anomaly injection."""

from audit_lakehouse.generator.anomalies import AnomalyFamily, inject_anomalies
from audit_lakehouse.generator.dataset import (
    SyntheticSwiftDataset,
    generate_synthetic_swift_dataset,
)
from audit_lakehouse.generator.mt540 import MT540Message, generate_mt540
from audit_lakehouse.generator.mt548 import MT548Message, SettlementStatus, generate_mt548_chain

__all__ = [
    "AnomalyFamily",
    "MT540Message",
    "MT548Message",
    "SettlementStatus",
    "SyntheticSwiftDataset",
    "generate_mt540",
    "generate_mt548_chain",
    "generate_synthetic_swift_dataset",
    "inject_anomalies",
]
