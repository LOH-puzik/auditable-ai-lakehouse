"""Deterministic re-scoring for replay.

The Isolation Forest is deterministic given the same fitted estimator and the
same input row — but only if numpy/sklearn versions match those captured in
the MLflow run's conda environment. The replay tool surfaces a warning, not an
error, if the runtime version differs from the logged version; the comparison
of scores against the logged score is what ultimately decides pass/fail.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from audit_lakehouse.lakehouse.gold import MODEL_FEATURE_COLUMNS


@dataclass(frozen=True)
class RescoreResult:
    score: float
    decision: str


def rescore(model: Any, feature_row: dict[str, Any]) -> RescoreResult:
    """Re-run the model on the reconstructed feature row."""
    feature_columns = _feature_columns(feature_row)
    missing = [column for column in feature_columns if column not in feature_row]
    if missing:
        raise ValueError(f"Feature row is missing model feature columns: {missing}")

    features = pd.DataFrame([{column: feature_row[column] for column in feature_columns}]).astype(
        float
    )
    prediction = int(model.predict(features)[0])
    if hasattr(model, "decision_function"):
        score = float(-model.decision_function(features)[0])
    else:
        score = 1.0 if prediction == -1 else 0.0

    return RescoreResult(
        score=score,
        decision="alert" if prediction == -1 else "clear",
    )


def _feature_columns(feature_row: dict[str, Any]) -> list[str]:
    declared_columns = feature_row.get("feature_columns")
    if isinstance(declared_columns, list) and declared_columns:
        return [str(column) for column in declared_columns]
    return MODEL_FEATURE_COLUMNS
