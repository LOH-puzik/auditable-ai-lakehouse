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

import math
import random
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from typing import Any


class AnomalyFamily(StrEnum):
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
    if not 0 <= rate <= 1:
        raise ValueError("rate must be between 0 and 1")

    output = [dict(record, anomaly_label=None) for record in records]
    if not output or rate == 0:
        return output

    family_choices = families or list(AnomalyFamily)
    if not family_choices:
        raise ValueError("families must contain at least one anomaly family")

    rng = random.Random(seed)
    anomaly_count = min(len(output), math.ceil(len(output) * rate))
    anomaly_indices = rng.sample(range(len(output)), anomaly_count)

    for index in anomaly_indices:
        family = rng.choice(family_choices)
        _apply_anomaly(output, index, family)

    return output


def _apply_anomaly(records: list[dict[str, Any]], index: int, family: AnomalyFamily) -> None:
    record = records[index]

    if family == AnomalyFamily.DUPLICATE_REFERENCE:
        _apply_duplicate_reference(records, index)
    elif family == AnomalyFamily.MISMATCHED_ISIN:
        record["mt548_isin"] = _different_isin(str(record.get("isin", "")))
    elif family == AnomalyFamily.LATE_SETTLEMENT:
        record["status"] = "PENF"
        record["reason_code"] = "LATE"
        record["reported_at"] = _late_reported_at(record.get("settlement_date"))
    elif family == AnomalyFamily.QUANTITY_OUTLIER:
        quantity = float(record.get("quantity") or 0.0)
        record["quantity"] = round(max(quantity * 100.0, 1_000_000.0), 2)
    elif family == AnomalyFamily.COUNTERPARTY_DRIFT:
        record["counterparty_bic"] = "DRFTGB2LXXX"
        record["counterparty_first_seen_days_ago"] = 0
    else:
        raise ValueError(f"Unsupported anomaly family: {family}")

    record["anomaly_label"] = family.value


def _apply_duplicate_reference(records: list[dict[str, Any]], index: int) -> None:
    if len(records) == 1:
        return
    source_index = index - 1 if index > 0 else 1
    records[index]["transaction_reference"] = records[source_index].get("transaction_reference")


def _different_isin(current_isin: str) -> str:
    candidates = [
        "US5949181045",
        "GB0002634946",
        "FR0000120271",
        "DE0007164600",
    ]
    for candidate in candidates:
        if candidate != current_isin:
            return candidate
    return "NL0000000000"


def _late_reported_at(settlement_date: Any) -> datetime:
    if isinstance(settlement_date, datetime):
        base = settlement_date.astimezone(UTC)
    elif isinstance(settlement_date, date):
        base = datetime.combine(settlement_date, time(hour=17), tzinfo=UTC)
    else:
        base = datetime(2026, 1, 2, 17, 0, tzinfo=UTC)
    return base + timedelta(days=7)
