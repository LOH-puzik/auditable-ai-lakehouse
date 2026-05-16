"""Tests for metric-gated model promotion."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from audit_lakehouse.modeling import promote_model


def test_promote_model_approves_and_emits_event(tmp_path) -> None:
    training_manifest = _write_training_manifest(
        tmp_path,
        metrics={"precision": 0.91, "recall": 0.82, "precision_at_k": 0.95},
    )

    result = promote_model(
        training_manifest,
        tmp_path / "registry" / "production",
        tmp_path / "events" / "promotion_events.jsonl",
        model_name="audit_lakehouse_isolation_forest",
        thresholds={"precision": 0.8, "recall": 0.7, "precision_at_k": 0.85},
        approver="approver@example.edu",
        promoted_at=datetime(2026, 1, 5, 12, 0, tzinfo=UTC),
        promotion_id="PROMOTE-TEST",
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    events = _read_jsonl(result.governance_events_path)

    assert result.approved is True
    assert result.event_written is True
    assert result.promoted_model_path.exists()
    assert result.gate_results == {
        "precision": True,
        "recall": True,
        "precision_at_k": True,
    }
    assert manifest["decision"] == "approved"
    assert manifest["to_stage"] == "Production"
    assert len(manifest["promotion_manifest_hash"]) == 64
    assert len(events) == 1
    assert events[0]["event_type"] == "promotion"
    assert events[0]["actor"] == "approver@example.edu"
    assert events[0]["payload"]["model_name"] == "audit_lakehouse_isolation_forest"
    assert events[0]["payload"]["to_stage"] == "Production"
    assert len(events[0]["event_hash"]) == 64


def test_promote_model_rejects_when_threshold_fails(tmp_path) -> None:
    training_manifest = _write_training_manifest(
        tmp_path,
        metrics={"precision": 0.91, "recall": 0.2, "precision_at_k": 0.95},
    )

    result = promote_model(
        training_manifest,
        tmp_path / "registry" / "production",
        tmp_path / "events" / "promotion_events.jsonl",
        model_name="audit_lakehouse_isolation_forest",
        thresholds={"precision": 0.8, "recall": 0.7, "precision_at_k": 0.85},
        approver="approver@example.edu",
        promoted_at=datetime(2026, 1, 5, tzinfo=UTC),
        promotion_id="PROMOTE-REJECT",
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

    assert result.approved is False
    assert result.event_written is False
    assert result.promoted_model_path.exists() is False
    assert result.gate_results["recall"] is False
    assert manifest["decision"] == "rejected"
    assert manifest["to_stage"] == "Staging"
    assert result.governance_events_path.read_text(encoding="utf-8") == ""


def test_promote_model_rejects_missing_training_manifest(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        promote_model(
            tmp_path / "missing_manifest.json",
            tmp_path / "registry",
            tmp_path / "events.jsonl",
            model_name="model",
            thresholds={"precision": 0.8},
            approver="approver",
        )


def test_promote_model_rejects_missing_metric(tmp_path) -> None:
    training_manifest = _write_training_manifest(
        tmp_path,
        metrics={"precision": 0.91},
    )

    with pytest.raises(ValueError, match="missing required threshold metric"):
        promote_model(
            training_manifest,
            tmp_path / "registry",
            tmp_path / "events.jsonl",
            model_name="model",
            thresholds={"precision": 0.8, "recall": 0.7},
            approver="approver",
        )


def test_promote_model_rejects_empty_thresholds(tmp_path) -> None:
    training_manifest = _write_training_manifest(
        tmp_path,
        metrics={"precision": 0.91},
    )

    with pytest.raises(ValueError, match="thresholds"):
        promote_model(
            training_manifest,
            tmp_path / "registry",
            tmp_path / "events.jsonl",
            model_name="model",
            thresholds={},
            approver="approver",
        )


def test_promote_model_rejects_naive_promotion_time(tmp_path) -> None:
    training_manifest = _write_training_manifest(
        tmp_path,
        metrics={"precision": 0.91},
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        promote_model(
            training_manifest,
            tmp_path / "registry",
            tmp_path / "events.jsonl",
            model_name="model",
            thresholds={"precision": 0.8},
            approver="approver",
            promoted_at=datetime(2026, 1, 5),
        )


def test_promote_model_rejects_missing_model_artifact_when_approved(tmp_path) -> None:
    training_manifest = _write_training_manifest(
        tmp_path,
        metrics={"precision": 0.91},
        create_model=False,
    )

    with pytest.raises(FileNotFoundError, match="model artifact"):
        promote_model(
            training_manifest,
            tmp_path / "registry",
            tmp_path / "events.jsonl",
            model_name="model",
            thresholds={"precision": 0.8},
            approver="approver",
        )


def _write_training_manifest(
    tmp_path: Path,
    *,
    metrics: dict[str, float],
    create_model: bool = True,
) -> Path:
    model_path = tmp_path / "training" / "model.joblib"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    if create_model:
        model_path.write_text("model-bytes", encoding="utf-8")

    manifest = {
        "training_run_id": "TRAIN-TEST",
        "model_path": str(model_path),
        "mlflow_run_id": "abc123",
        "mlflow_model_uri": "runs:/abc123/model",
        "metrics": metrics,
    }
    manifest_path = tmp_path / "training" / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
