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


@dataclass(frozen=True)
class RescoreResult:
    score: float
    decision: str


def rescore(model: Any, feature_row: dict[str, Any]) -> RescoreResult:
    """Re-run the model on the reconstructed feature row."""
    raise NotImplementedError("Implement in step 6 of the build plan")
