"""Tests for Isolation Forest training and evaluation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import joblib
import pytest

from audit_lakehouse.generator import generate_synthetic_swift_dataset
from audit_lakehouse.lakehouse import (
    build_gold_features,
    ingest_bronze_raw_messages,
    parse_validate_silver,
)
from audit_lakehouse.modeling import train_isolation_forest


def test_train_isolation_forest_writes_artifacts_and_metrics(tmp_path) -> None:
    gold_records_path = _build_gold_records(tmp_path, n=30, seed=61, anomaly_rate=0.2)

    result = train_isolation_forest(
        gold_records_path,
        tmp_path / "model",
        tracking_uri=(tmp_path / "mlruns").resolve().as_uri(),
        experiment_name="test-isolation-forest",
        seed=61,
        contamination=0.2,
        n_estimators=25,
        training_run_id="TRAIN-TEST",
        trained_at=datetime(2026, 1, 4, 12, 0, tzinfo=UTC),
    )

    assert result.rows_read == 30
    assert result.training_run_id == "TRAIN-TEST"
    assert result.model_path.exists()
    assert result.metrics_path.exists()
    assert result.predictions_path.exists()
    assert result.manifest_path.exists()
    assert result.mlflow_run_id
    assert result.mlflow_model_uri == f"runs:/{result.mlflow_run_id}/model"

    metrics = json.loads(result.metrics_path.read_text(encoding="utf-8"))
    predictions = _read_jsonl(result.predictions_path)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

    assert set(metrics) >= {
        "precision",
        "recall",
        "precision_at_k",
        "actual_anomalies",
        "predicted_anomalies",
        "rows_scored",
    }
    assert metrics["rows_scored"] == 30.0
    assert metrics["actual_anomalies"] > 0.0
    assert len(predictions) == 30
    assert len(predictions[0]["feature_row_hash"]) == 64
    assert manifest["training_run_id"] == "TRAIN-TEST"
    assert len(manifest["training_manifest_hash"]) == 64

    model = joblib.load(result.model_path)
    assert hasattr(model, "predict")


def test_train_isolation_forest_is_deterministic_for_same_input(tmp_path) -> None:
    gold_records_path = _build_gold_records(tmp_path, n=20, seed=62, anomaly_rate=0.2)

    first = train_isolation_forest(
        gold_records_path,
        tmp_path / "model_1",
        tracking_uri=(tmp_path / "mlruns_1").resolve().as_uri(),
        experiment_name="test-isolation-forest-1",
        seed=62,
        contamination=0.2,
        n_estimators=15,
        training_run_id="TRAIN-1",
        trained_at=datetime(2026, 1, 4, tzinfo=UTC),
    )
    second = train_isolation_forest(
        gold_records_path,
        tmp_path / "model_2",
        tracking_uri=(tmp_path / "mlruns_2").resolve().as_uri(),
        experiment_name="test-isolation-forest-2",
        seed=62,
        contamination=0.2,
        n_estimators=15,
        training_run_id="TRAIN-2",
        trained_at=datetime(2026, 1, 5, tzinfo=UTC),
    )

    first_predictions = _read_jsonl(first.predictions_path)
    second_predictions = _read_jsonl(second.predictions_path)

    assert [row["anomaly_score"] for row in first_predictions] == [
        row["anomaly_score"] for row in second_predictions
    ]
    assert [row["predicted_is_anomaly"] for row in first_predictions] == [
        row["predicted_is_anomaly"] for row in second_predictions
    ]


def test_train_isolation_forest_rejects_missing_input(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        train_isolation_forest(
            tmp_path / "missing.jsonl",
            tmp_path / "model",
            tracking_uri=(tmp_path / "mlruns").resolve().as_uri(),
            experiment_name="test",
        )


def test_train_isolation_forest_rejects_invalid_contamination(tmp_path) -> None:
    gold_records_path = _build_gold_records(tmp_path, n=5, seed=63, anomaly_rate=0.2)

    with pytest.raises(ValueError, match="contamination"):
        train_isolation_forest(
            gold_records_path,
            tmp_path / "model",
            tracking_uri=(tmp_path / "mlruns").resolve().as_uri(),
            experiment_name="test",
            contamination=0.8,
        )


def test_train_isolation_forest_rejects_naive_training_time(tmp_path) -> None:
    gold_records_path = _build_gold_records(tmp_path, n=5, seed=64, anomaly_rate=0.2)

    with pytest.raises(ValueError, match="timezone-aware"):
        train_isolation_forest(
            gold_records_path,
            tmp_path / "model",
            tracking_uri=(tmp_path / "mlruns").resolve().as_uri(),
            experiment_name="test",
            trained_at=datetime(2026, 1, 4),
        )


def test_train_isolation_forest_rejects_empty_input(tmp_path) -> None:
    gold_records_path = tmp_path / "empty.jsonl"
    gold_records_path.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="empty"):
        train_isolation_forest(
            gold_records_path,
            tmp_path / "model",
            tracking_uri=(tmp_path / "mlruns").resolve().as_uri(),
            experiment_name="test",
        )


def _build_gold_records(
    tmp_path: Path,
    *,
    n: int,
    seed: int,
    anomaly_rate: float,
) -> Path:
    dataset = generate_synthetic_swift_dataset(n, seed=seed, anomaly_rate=anomaly_rate)
    raw_paths = dataset.write_jsonl(tmp_path / f"raw_{seed}")
    bronze = ingest_bronze_raw_messages(
        raw_paths["raw_messages"],
        tmp_path / f"bronze_{seed}",
        batch_id=f"BRONZE-{seed}",
        ingested_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    silver = parse_validate_silver(
        bronze.records_path,
        tmp_path / f"silver_{seed}",
        tmp_path / f"quarantine_{seed}",
        tmp_path / f"events_{seed}" / "quarantine_events.jsonl",
        validation_batch_id=f"SILVER-{seed}",
        validated_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    gold = build_gold_features(
        silver.instructions_path,
        silver.statuses_path,
        tmp_path / f"gold_{seed}",
        gold_snapshot_id=f"GOLD-{seed}",
        built_at=datetime(2026, 1, 3, tzinfo=UTC),
    )
    return gold.records_path


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
