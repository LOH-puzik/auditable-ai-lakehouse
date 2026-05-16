"""Metric-gated model promotion and governance-event emission."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from swift_audit.events import PromotionEvent
from swift_audit.hashing import sha256_hex


@dataclass(frozen=True)
class ModelPromotionResult:
    """Artifacts and decision produced by a promotion gate run."""

    training_manifest_path: Path
    output_dir: Path
    manifest_path: Path
    governance_events_path: Path
    promoted_model_path: Path
    promotion_id: str
    approved: bool
    gate_results: dict[str, bool]
    event_written: bool


def promote_model(
    training_manifest_path: str | Path,
    output_dir: str | Path,
    governance_events_path: str | Path,
    *,
    model_name: str,
    thresholds: dict[str, float],
    approver: str,
    from_stage: str = "Staging",
    to_stage: str = "Production",
    promoted_at: datetime | None = None,
    promotion_id: str | None = None,
) -> ModelPromotionResult:
    """Promote a trained model only if its metrics satisfy all thresholds."""
    manifest_source = Path(training_manifest_path)
    target_dir = Path(output_dir)
    events_path = Path(governance_events_path)
    if not manifest_source.exists():
        raise FileNotFoundError(f"Training manifest does not exist: {manifest_source}")
    if not thresholds:
        raise ValueError("thresholds must not be empty")

    promotion_time = promoted_at or datetime.now(UTC)
    if promotion_time.tzinfo is None:
        raise ValueError("promoted_at must be timezone-aware")
    promotion_time = promotion_time.astimezone(UTC)
    promotion_run_id = promotion_id or f"PROMOTE-{promotion_time.strftime('%Y%m%d%H%M%S')}"

    training_manifest = json.loads(manifest_source.read_text(encoding="utf-8"))
    metrics = _coerce_float_dict(training_manifest.get("metrics", {}), "metrics")
    gate_results = _evaluate_thresholds(metrics, thresholds)
    approved = all(gate_results.values())

    source_model_path = Path(str(training_manifest.get("model_path", "")))
    if approved and not source_model_path.exists():
        raise FileNotFoundError(f"Trained model artifact does not exist: {source_model_path}")

    target_dir.mkdir(parents=True, exist_ok=True)
    events_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = target_dir / "manifest.json"
    promoted_model_path = target_dir / "model.joblib"

    if approved:
        shutil.copy2(source_model_path, promoted_model_path)

    decision = "approved" if approved else "rejected"
    promotion_manifest = {
        "stage": "promote_model",
        "promotion_id": promotion_run_id,
        "decision": decision,
        "approved": approved,
        "promoted_at": promotion_time,
        "model_name": model_name,
        "model_version": str(training_manifest.get("training_run_id", promotion_run_id)),
        "from_stage": from_stage,
        "to_stage": to_stage if approved else from_stage,
        "approver": approver,
        "training_manifest_path": str(manifest_source),
        "source_model_path": str(source_model_path),
        "promoted_model_path": str(promoted_model_path) if approved else "",
        "mlflow_run_id": str(training_manifest.get("mlflow_run_id", "")),
        "mlflow_model_uri": str(training_manifest.get("mlflow_model_uri", "")),
        "metrics": metrics,
        "thresholds": thresholds,
        "gate_results": gate_results,
        "promotion_manifest_hash": sha256_hex(
            {
                "promotion_id": promotion_run_id,
                "decision": decision,
                "model_name": model_name,
                "model_version": str(training_manifest.get("training_run_id", promotion_run_id)),
                "metrics": metrics,
                "thresholds": thresholds,
                "gate_results": gate_results,
            }
        ),
    }

    manifest_path.write_text(
        json.dumps(_json_ready(promotion_manifest), indent=2, sort_keys=True),
        encoding="utf-8",
    )

    event_written = False
    if approved:
        event = _build_promotion_event(promotion_manifest)
        _write_jsonl(events_path, [event])
        event_written = True
    else:
        _write_jsonl(events_path, [])

    return ModelPromotionResult(
        training_manifest_path=manifest_source,
        output_dir=target_dir,
        manifest_path=manifest_path,
        governance_events_path=events_path,
        promoted_model_path=promoted_model_path,
        promotion_id=promotion_run_id,
        approved=approved,
        gate_results=gate_results,
        event_written=event_written,
    )


def _evaluate_thresholds(
    metrics: dict[str, float],
    thresholds: dict[str, float],
) -> dict[str, bool]:
    gate_results: dict[str, bool] = {}
    for metric_name, threshold in thresholds.items():
        if metric_name not in metrics:
            raise ValueError(
                f"Training metrics are missing required threshold metric: {metric_name}"
            )
        gate_results[metric_name] = metrics[metric_name] >= float(threshold)
    return gate_results


def _build_promotion_event(manifest: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "promotion_id": str(manifest["promotion_id"]),
        "model_name": str(manifest["model_name"]),
        "model_version": str(manifest["model_version"]),
        "from_stage": str(manifest["from_stage"]),
        "to_stage": str(manifest["to_stage"]),
        "metrics": _coerce_float_dict(manifest["metrics"], "metrics"),
        "thresholds": _coerce_float_dict(manifest["thresholds"], "thresholds"),
        "gate_results": {str(key): bool(value) for key, value in manifest["gate_results"].items()},
        "mlflow_run_id": str(manifest["mlflow_run_id"]),
        "mlflow_model_uri": str(manifest["mlflow_model_uri"]),
        "promoted_model_path": str(manifest["promoted_model_path"]),
        "promotion_manifest_hash": str(manifest["promotion_manifest_hash"]),
    }
    event = PromotionEvent(actor=str(manifest["approver"]), payload=payload)
    data = event.model_dump(mode="json")
    data["event_hash"] = event.to_hash()
    return data


def _coerce_float_dict(value: Any, name: str) -> dict[str, float]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a dictionary")
    return {str(key): float(item) for key, item in value.items()}


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    lines = [json.dumps(_json_ready(record), sort_keys=True) for record in records]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _json_ready(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    return value
