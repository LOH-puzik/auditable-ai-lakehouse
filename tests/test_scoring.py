"""Tests for scoring and inference event logging."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import joblib
import pandas as pd
import pytest
from sklearn.ensemble import IsolationForest
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from swift_audit.generator import generate_synthetic_swift_dataset
from swift_audit.lakehouse import (
    build_gold_features,
    ingest_bronze_raw_messages,
    parse_validate_silver,
)
from swift_audit.lakehouse.gold import MODEL_FEATURE_COLUMNS
from swift_audit.modeling import score_gold_features


def test_score_gold_features_writes_scored_rows_and_events(tmp_path) -> None:
    gold_records_path = _build_gold_records(tmp_path, n=10, seed=71, anomaly_rate=0.2)
    promotion_manifest = _build_promotion_manifest(tmp_path, gold_records_path)

    result = score_gold_features(
        gold_records_path,
        promotion_manifest,
        tmp_path / "scoring",
        tmp_path / "events" / "inference_events.jsonl",
        scoring_batch_id="SCORE-TEST",
        scored_at=datetime(2026, 1, 6, 12, 0, tzinfo=UTC),
        actor="test_scoring_job",
    )

    scored = _read_jsonl(result.scored_records_path)
    events = _read_jsonl(result.governance_events_path)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

    assert result.records_read == 10
    assert result.records_scored == 10
    assert result.events_written == 10
    assert len(scored) == 10
    assert len(events) == 10
    assert manifest["scoring_batch_id"] == "SCORE-TEST"
    assert manifest["events_written"] == 10
    assert scored[0]["alert_id"] == "ALERT-SCORE-TEST-00000000"
    assert scored[0]["scored_at"] == "2026-01-06T12:00:00+00:00"
    assert scored[0]["decision"] in {"alert", "clear"}
    assert len(scored[0]["input_hash"]) == 64
    assert events[0]["event_type"] == "inference"
    assert events[0]["actor"] == "test_scoring_job"
    assert events[0]["payload"]["alert_id"] == scored[0]["alert_id"]
    assert events[0]["payload"]["input_hash"] == scored[0]["input_hash"]
    assert events[0]["payload"]["model_name"] == "swift_audit_isolation_forest"
    assert len(events[0]["event_hash"]) == 64


def test_score_gold_features_rejects_unapproved_promotion(tmp_path) -> None:
    gold_records_path = _build_gold_records(tmp_path, n=5, seed=72, anomaly_rate=0.2)
    promotion_manifest = _build_promotion_manifest(
        tmp_path,
        gold_records_path,
        approved=False,
    )

    with pytest.raises(ValueError, match="not approved"):
        score_gold_features(
            gold_records_path,
            promotion_manifest,
            tmp_path / "scoring",
            tmp_path / "events.jsonl",
        )


def test_score_gold_features_rejects_missing_inputs(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        score_gold_features(
            tmp_path / "missing_gold.jsonl",
            tmp_path / "missing_promotion.json",
            tmp_path / "scoring",
            tmp_path / "events.jsonl",
        )


def test_score_gold_features_rejects_missing_model_artifact(tmp_path) -> None:
    gold_records_path = _build_gold_records(tmp_path, n=5, seed=73, anomaly_rate=0.2)
    promotion_manifest = _build_promotion_manifest(
        tmp_path,
        gold_records_path,
        create_model=False,
    )

    with pytest.raises(FileNotFoundError, match="Promoted model artifact"):
        score_gold_features(
            gold_records_path,
            promotion_manifest,
            tmp_path / "scoring",
            tmp_path / "events.jsonl",
        )


def test_score_gold_features_rejects_naive_scoring_time(tmp_path) -> None:
    gold_records_path = _build_gold_records(tmp_path, n=5, seed=74, anomaly_rate=0.2)
    promotion_manifest = _build_promotion_manifest(tmp_path, gold_records_path)

    with pytest.raises(ValueError, match="timezone-aware"):
        score_gold_features(
            gold_records_path,
            promotion_manifest,
            tmp_path / "scoring",
            tmp_path / "events.jsonl",
            scored_at=datetime(2026, 1, 6),
        )


def test_score_gold_features_rejects_empty_gold_input(tmp_path) -> None:
    gold_records_path = tmp_path / "empty_gold.jsonl"
    gold_records_path.write_text("", encoding="utf-8")
    promotion_manifest = _build_promotion_manifest(tmp_path, gold_records_path)

    with pytest.raises(ValueError, match="empty"):
        score_gold_features(
            gold_records_path,
            promotion_manifest,
            tmp_path / "scoring",
            tmp_path / "events.jsonl",
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


def _build_promotion_manifest(
    tmp_path: Path,
    gold_records_path: Path,
    *,
    approved: bool = True,
    create_model: bool = True,
) -> Path:
    registry_dir = tmp_path / "registry"
    registry_dir.mkdir(parents=True, exist_ok=True)
    model_path = registry_dir / "model.joblib"

    gold_records = _read_jsonl(gold_records_path) if gold_records_path.exists() else []
    if create_model:
        model = Pipeline(
            steps=[
                ("scaler", StandardScaler()),
                (
                    "isolation_forest",
                    IsolationForest(
                        n_estimators=10,
                        contamination=0.2,
                        random_state=42,
                    ),
                ),
            ]
        )
        if gold_records:
            frame = pd.DataFrame(gold_records)
            model.fit(frame[MODEL_FEATURE_COLUMNS].astype(float))
        else:
            model.fit(
                pd.DataFrame([[0.0] * len(MODEL_FEATURE_COLUMNS)], columns=MODEL_FEATURE_COLUMNS)
            )
        joblib.dump(model, model_path)

    manifest = {
        "approved": approved,
        "promotion_id": "PROMOTE-TEST",
        "promotion_manifest_hash": "a" * 64,
        "model_name": "swift_audit_isolation_forest",
        "model_version": "TRAIN-TEST",
        "promoted_model_path": str(model_path),
    }
    manifest_path = registry_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
