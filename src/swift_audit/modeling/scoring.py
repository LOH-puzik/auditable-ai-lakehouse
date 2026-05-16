"""Score Gold feature rows with the promoted model and emit inference events."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
from sklearn.pipeline import Pipeline

from swift_audit.events import InferenceEvent
from swift_audit.lakehouse.gold import MODEL_FEATURE_COLUMNS


@dataclass(frozen=True)
class InferenceScoringResult:
    """Artifacts and row counts produced by a scoring run."""

    gold_records_path: Path
    promotion_manifest_path: Path
    output_dir: Path
    scored_records_path: Path
    governance_events_path: Path
    manifest_path: Path
    scoring_batch_id: str
    records_read: int
    records_scored: int
    events_written: int
    alerts_generated: int


def score_gold_features(
    gold_records_path: str | Path,
    promotion_manifest_path: str | Path,
    output_dir: str | Path,
    governance_events_path: str | Path,
    *,
    scoring_batch_id: str | None = None,
    scored_at: datetime | None = None,
    actor: str = "scoring_job",
) -> InferenceScoringResult:
    """Score Gold rows with the promoted model and emit one InferenceEvent per row."""
    gold_source = Path(gold_records_path)
    promotion_source = Path(promotion_manifest_path)
    target_dir = Path(output_dir)
    events_path = Path(governance_events_path)
    if not gold_source.exists():
        raise FileNotFoundError(f"Gold feature input does not exist: {gold_source}")
    if not promotion_source.exists():
        raise FileNotFoundError(f"Promotion manifest does not exist: {promotion_source}")

    scoring_time = scored_at or datetime.now(UTC)
    if scoring_time.tzinfo is None:
        raise ValueError("scored_at must be timezone-aware")
    scoring_time = scoring_time.astimezone(UTC)
    batch_id = scoring_batch_id or f"SCORE-{scoring_time.strftime('%Y%m%d%H%M%S')}"

    gold_records = _read_jsonl(gold_source)
    if not gold_records:
        raise ValueError("Gold feature input is empty")

    promotion_manifest = json.loads(promotion_source.read_text(encoding="utf-8"))
    if not promotion_manifest.get("approved", False):
        raise ValueError("Promotion manifest is not approved; refusing to score")

    model_path = Path(str(promotion_manifest.get("promoted_model_path", "")))
    if not model_path.exists():
        raise FileNotFoundError(f"Promoted model artifact does not exist: {model_path}")

    model = joblib.load(model_path)
    if not isinstance(model, Pipeline) and not hasattr(model, "predict"):
        raise TypeError("Promoted model must expose a predict method")

    feature_columns = _feature_columns_from_records(gold_records)
    frame = pd.DataFrame(gold_records)
    features = frame[feature_columns].astype(float)
    predictions = model.predict(features)
    scores = _anomaly_scores(model, features)

    scored_records: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    model_name = str(promotion_manifest["model_name"])
    model_version = str(promotion_manifest["model_version"])

    for sequence, row in enumerate(gold_records):
        predicted_is_anomaly = bool(predictions[sequence] == -1)
        decision = "alert" if predicted_is_anomaly else "clear"
        alert_id = f"ALERT-{batch_id}-{sequence:08d}"
        score = float(scores[sequence])
        scored_record = {
            "alert_id": alert_id,
            "scoring_batch_id": batch_id,
            "scored_at": scoring_time,
            "decision": decision,
            "score": score,
            "predicted_is_anomaly": predicted_is_anomaly,
            "model_name": model_name,
            "model_version": model_version,
            "gold_record_id": row["gold_record_id"],
            "gold_snapshot_id": row["gold_snapshot_id"],
            "transaction_reference": row["transaction_reference"],
            "input_hash": row["feature_row_hash"],
            "feature_row_hash": row["feature_row_hash"],
            "true_is_anomaly": bool(row.get("is_anomaly", False)),
            "anomaly_label": row.get("anomaly_label"),
        }
        scored_records.append(scored_record)
        events.append(
            _build_inference_event(
                scored_record,
                actor=actor,
                promotion_manifest=promotion_manifest,
            )
        )

    target_dir.mkdir(parents=True, exist_ok=True)
    events_path.parent.mkdir(parents=True, exist_ok=True)
    scored_records_path = target_dir / "records.jsonl"
    manifest_path = target_dir / "manifest.json"

    _write_jsonl(scored_records_path, scored_records)
    _write_jsonl(events_path, events)

    manifest = {
        "stage": "score_gold_features",
        "scoring_batch_id": batch_id,
        "scored_at": scoring_time,
        "gold_records_path": str(gold_source),
        "promotion_manifest_path": str(promotion_source),
        "scored_records_path": str(scored_records_path),
        "governance_events_path": str(events_path),
        "records_read": len(gold_records),
        "records_scored": len(scored_records),
        "events_written": len(events),
        "alerts_generated": sum(1 for row in scored_records if row["decision"] == "alert"),
        "model_name": model_name,
        "model_version": model_version,
        "feature_columns": feature_columns,
    }
    manifest_path.write_text(
        json.dumps(_json_ready(manifest), indent=2, sort_keys=True),
        encoding="utf-8",
    )

    return InferenceScoringResult(
        gold_records_path=gold_source,
        promotion_manifest_path=promotion_source,
        output_dir=target_dir,
        scored_records_path=scored_records_path,
        governance_events_path=events_path,
        manifest_path=manifest_path,
        scoring_batch_id=batch_id,
        records_read=len(gold_records),
        records_scored=len(scored_records),
        events_written=len(events),
        alerts_generated=manifest["alerts_generated"],
    )


def _feature_columns_from_records(records: list[dict[str, Any]]) -> list[str]:
    declared_columns = records[0].get("feature_columns")
    feature_columns = (
        [str(column) for column in declared_columns]
        if isinstance(declared_columns, list) and declared_columns
        else MODEL_FEATURE_COLUMNS
    )
    missing = [column for column in feature_columns if column not in records[0]]
    if missing:
        raise ValueError(f"Gold feature records are missing feature columns: {missing}")
    return feature_columns


def _anomaly_scores(model: Any, features: pd.DataFrame) -> list[float]:
    if hasattr(model, "decision_function"):
        return [float(value) for value in -model.decision_function(features)]
    predictions = model.predict(features)
    return [1.0 if prediction == -1 else 0.0 for prediction in predictions]


def _build_inference_event(
    scored_record: dict[str, Any],
    *,
    actor: str,
    promotion_manifest: dict[str, Any],
) -> dict[str, Any]:
    payload = {
        "alert_id": str(scored_record["alert_id"]),
        "input_hash": str(scored_record["input_hash"]),
        "gold_snapshot_version": str(scored_record["gold_snapshot_id"]),
        "gold_snapshot_id": str(scored_record["gold_snapshot_id"]),
        "gold_record_id": str(scored_record["gold_record_id"]),
        "model_name": str(scored_record["model_name"]),
        "model_version": str(scored_record["model_version"]),
        "score": float(scored_record["score"]),
        "decision": str(scored_record["decision"]),
        "promotion_id": str(promotion_manifest["promotion_id"]),
        "promotion_manifest_hash": str(promotion_manifest["promotion_manifest_hash"]),
    }
    event = InferenceEvent(actor=actor, payload=payload)
    data = event.model_dump(mode="json")
    data["event_hash"] = event.to_hash()
    return data


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
