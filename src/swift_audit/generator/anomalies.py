"""Controlled anomaly injection.

Injects labelled anomalies into a synthetic dataset so that the Isolation Forest
can be evaluated against ground truth. Each anomaly carries an `anomaly_label`
field so precision, recall, and precision@k can be computed in evaluation.

Anomaly families:
  - duplicate_reference: identical :20C reference seen within a short window
  - mismatched_isin: MT548 references an ISIN not present in the matched MT540
  - late_settlement: MT548 status remains PENDING well past settlement date
  - quantity_outlier: settlement quantity orders of magnitude above peer median
  - counterparty_drift: counterparty BIC has not been seen in N days
"""

from __future__ import annotations

from enum import Enum


class AnomalyFamily(str, Enum):
    DUPLICATE_REFERENCE = "duplicate_reference"
    MISMATCHED_ISIN = "mismatched_isin"
    LATE_SETTLEMENT = "late_settlement"
    QUANTITY_OUTLIER = "quantity_outlier"
    COUNTERPARTY_DRIFT = "counterparty_drift"


def inject_anomalies(
    records: list[dict],
    *,
    rate: float = 0.02,
    families: list[AnomalyFamily] | None = None,
    seed: int = 42,
) -> list[dict]:
    """Inject anomalies into a list of records at the specified rate.

    Returns the records with an `anomaly_label` field added to each (the label
    is the family name, or None for normal records).
    """
    raise NotImplementedError("Implement in step 1 of the build plan")
