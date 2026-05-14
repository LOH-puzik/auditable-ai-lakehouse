"""Snapshot and model loading for replay.

Loading rules:
  - Gold features come from Delta time-travel: `versionAsOf` the snapshot version
    recorded in the InferenceEvent payload.
  - Model artifacts come from the MLflow registry: load by exact version, not
    by stage (a model promoted out of Production after the alert was generated
    must still be reachable for replay).
  - Both lookups are read-only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LoadedSnapshot:
    """A reconstructed scoring context: the input row plus the model used."""

    alert_id: str
    feature_row: dict[str, Any]
    feature_row_hash: str
    model_name: str
    model_version: int
    model: Any  # the loaded sklearn estimator


def load_for_alert(alert_id: str) -> LoadedSnapshot:
    """Resolve an alert_id into its full scoring context."""
    raise NotImplementedError("Implement in step 6 of the build plan")
