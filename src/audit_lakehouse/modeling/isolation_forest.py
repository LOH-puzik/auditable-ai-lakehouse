"""Train and evaluate the Isolation Forest anomaly detector."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import mlflow
import mlflow.sklearn
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from audit_lakehouse.hashing import sha256_hex
from audit_lakehouse.lakehouse.gold import MODEL_FEATURE_COLUMNS


@dataclass(frozen=True)
class IsolationForestTrainingResult:
    """Artifacts and metrics produced by a training run."""

    gold_records_path: Path
    output_dir: Path
    model_path: Path
    metrics_path: Path
    predictions_path: Path
    manifest_path: Path
    mlflow_run_id: str
    mlflow_model_uri: str
    metrics: dict[str, float]
    feature_columns: list[str]
    training_run_id: str
    rows_read: int


def train_isolation_forest(
    gold_records_path: str | Path,
    output_dir: str | Path,
    *,
    tracking_uri: str,
    experiment_name: str,
    seed: int = 42,
    contamination: float = 0.05,
    n_estimators: int = 200,
    training_run_id: str | None = None,
    trained_at: datetime | None = None,
) -> IsolationForestTrainingResult:
    """Train an Isolation Forest from Gold feature records and log to MLflow."""
    source_path = Path(gold_records_path)
    target_dir = Path(output_dir)
    if not source_path.exists():
        raise FileNotFoundError(f"Gold feature input does not exist: {source_path}")
    if not 0 < contamination < 0.5:
        raise ValueError("contamination must be between 0 and 0.5")

    train_time = trained_at or datetime.now(UTC)
    if train_time.tzinfo is None:
        raise ValueError("trained_at must be timezone-aware")
    train_time = train_time.astimezone(UTC)
    run_id = training_run_id or f"TRAIN-{train_time.strftime('%Y%m%d%H%M%S')}"

    records = _read_jsonl(source_path)
    if not records:
        raise ValueError("Gold feature input is empty")

    feature_columns = _feature_columns_from_records(records)
    frame = pd.DataFrame(records)
    features = frame[feature_columns].astype(float)
    labels = frame["is_anomaly"].astype(bool).to_numpy()

    model = Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            (
                "isolation_forest",
                IsolationForest(
                    n_estimators=n_estimators,
                    contamination=contamination,
                    random_state=seed,
                ),
            ),
        ]
    )
    model.fit(features)

    predictions = _score_records(model, frame, feature_columns, labels)
    metrics = _compute_metrics(predictions)

    target_dir.mkdir(parents=True, exist_ok=True)
    model_path = target_dir / "model.joblib"
    metrics_path = target_dir / "metrics.json"
    predictions_path = target_dir / "predictions.jsonl"
    manifest_path = target_dir / "manifest.json"

    joblib.dump(model, model_path)
    metrics_path.write_text(
        json.dumps(metrics, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    _write_jsonl(predictions_path, predictions)

    mlflow_run_id, mlflow_model_uri = _log_mlflow_run(
        model,
        metrics=metrics,
        params={
            "seed": seed,
            "contamination": contamination,
            "n_estimators": n_estimators,
            "feature_count": len(feature_columns),
            "rows_read": len(records),
            "training_run_id": run_id,
        },
        tracking_uri=tracking_uri,
        experiment_name=experiment_name,
        gold_records_path=source_path,
        feature_columns=feature_columns,
    )

    manifest = {
        "stage": "train_isolation_forest",
        "training_run_id": run_id,
        "trained_at": train_time,
        "gold_records_path": str(source_path),
        "rows_read": len(records),
        "feature_columns": feature_columns,
        "model_path": str(model_path),
        "metrics_path": str(metrics_path),
        "predictions_path": str(predictions_path),
        "mlflow_tracking_uri": tracking_uri,
        "mlflow_experiment_name": experiment_name,
        "mlflow_run_id": mlflow_run_id,
        "mlflow_model_uri": mlflow_model_uri,
        "metrics": metrics,
        "training_manifest_hash": sha256_hex(
            {
                "training_run_id": run_id,
                "feature_columns": feature_columns,
                "metrics": metrics,
                "gold_feature_hashes": [record["feature_row_hash"] for record in records],
            }
        ),
    }
    manifest_path.write_text(
        json.dumps(_json_ready(manifest), indent=2, sort_keys=True),
        encoding="utf-8",
    )

    return IsolationForestTrainingResult(
        gold_records_path=source_path,
        output_dir=target_dir,
        model_path=model_path,
        metrics_path=metrics_path,
        predictions_path=predictions_path,
        manifest_path=manifest_path,
        mlflow_run_id=mlflow_run_id,
        mlflow_model_uri=mlflow_model_uri,
        metrics=metrics,
        feature_columns=feature_columns,
        training_run_id=run_id,
        rows_read=len(records),
    )


def _feature_columns_from_records(records: list[dict[str, Any]]) -> list[str]:
    declared_columns = records[0].get("feature_columns")
    if isinstance(declared_columns, list) and declared_columns:
        feature_columns = [str(column) for column in declared_columns]
    else:
        feature_columns = MODEL_FEATURE_COLUMNS

    missing = [column for column in feature_columns if column not in records[0]]
    if missing:
        raise ValueError(f"Gold feature records are missing feature columns: {missing}")
    return feature_columns


def _score_records(
    model: Pipeline,
    frame: pd.DataFrame,
    feature_columns: list[str],
    labels: np.ndarray,
) -> list[dict[str, Any]]:
    features = frame[feature_columns].astype(float)
    predictions = model.predict(features)
    anomaly_scores = -model.decision_function(features)

    rows: list[dict[str, Any]] = []
    for index, row in frame.iterrows():
        rows.append(
            {
                "gold_record_id": row["gold_record_id"],
                "gold_snapshot_id": row["gold_snapshot_id"],
                "transaction_reference": row["transaction_reference"],
                "feature_row_hash": row["feature_row_hash"],
                "true_is_anomaly": bool(labels[index]),
                "predicted_is_anomaly": bool(predictions[index] == -1),
                "anomaly_score": float(anomaly_scores[index]),
                "anomaly_label": row.get("anomaly_label"),
            }
        )
    return rows


def _compute_metrics(predictions: list[dict[str, Any]]) -> dict[str, float]:
    true_positive = sum(
        1 for row in predictions if row["true_is_anomaly"] and row["predicted_is_anomaly"]
    )
    predicted_positive = sum(1 for row in predictions if row["predicted_is_anomaly"])
    actual_positive = sum(1 for row in predictions if row["true_is_anomaly"])

    precision = true_positive / predicted_positive if predicted_positive else 0.0
    recall = true_positive / actual_positive if actual_positive else 0.0
    k = actual_positive if actual_positive else min(10, len(predictions))
    top_k = sorted(predictions, key=lambda row: row["anomaly_score"], reverse=True)[:k]
    precision_at_k = sum(1 for row in top_k if row["true_is_anomaly"]) / k if k else 0.0

    return {
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "precision_at_k": round(precision_at_k, 6),
        "actual_anomalies": float(actual_positive),
        "predicted_anomalies": float(predicted_positive),
        "rows_scored": float(len(predictions)),
    }


def _log_mlflow_run(
    model: Pipeline,
    *,
    metrics: dict[str, float],
    params: dict[str, Any],
    tracking_uri: str,
    experiment_name: str,
    gold_records_path: Path,
    feature_columns: list[str],
) -> tuple[str, str]:
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(experiment_name)
    with mlflow.start_run() as run:
        mlflow.log_params(params)
        mlflow.log_metrics(metrics)
        mlflow.log_text("\n".join(feature_columns), "feature_columns.txt")
        mlflow.log_param("gold_records_path", str(gold_records_path))
        mlflow.sklearn.log_model(model, artifact_path="model")
        return run.info.run_id, f"runs:/{run.info.run_id}/model"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON on line {line_number} of {path}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"Expected JSON object on line {line_number} of {path}")
        records.append(value)
    return records


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
