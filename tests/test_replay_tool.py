"""Tests for the end-to-end replay tool."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from audit_lakehouse.anchoring import build_anchor_batch
from audit_lakehouse.generator import generate_synthetic_swift_dataset
from audit_lakehouse.lakehouse import (
    build_gold_features,
    ingest_bronze_raw_messages,
    parse_validate_silver,
)
from audit_lakehouse.lakehouse.gold import MODEL_FEATURE_COLUMNS
from audit_lakehouse.modeling import score_gold_features
from audit_lakehouse.replay.cli import replay_alert, replay_batch


def test_replay_alert_passes_for_complete_local_evidence(tmp_path, monkeypatch) -> None:
    evidence = _build_replay_evidence(tmp_path)
    _set_replay_env(monkeypatch, evidence)

    report = replay_alert(evidence["alert_id"])

    assert report.passed is True
    assert report.input_hash_match is True
    assert report.deterministic_score_match is True
    assert report.merkle_proof_valid is True
    assert report.onchain_root_match is True
    assert report.batch_id == "BATCH-REPLAY"
    assert report.tx_hash == "0x" + "d" * 64


def test_replay_batch_replays_all_inference_events(tmp_path, monkeypatch) -> None:
    evidence = _build_replay_evidence(tmp_path)
    _set_replay_env(monkeypatch, evidence)

    report = replay_batch("BATCH-REPLAY")

    assert report.passed is True
    assert report.batch_id == "BATCH-REPLAY"
    assert len(report.reports) == evidence["event_count"]
    assert all(item.passed for item in report.reports)


def test_replay_detects_tampered_anchored_event(tmp_path, monkeypatch) -> None:
    evidence = _build_replay_evidence(tmp_path)
    _set_replay_env(monkeypatch, evidence)
    manifest = json.loads((evidence["anchor_batches_dir"] / "latest" / "manifest.json").read_text())
    events_path = Path(manifest["events_path"])
    events = _read_jsonl(events_path)
    event = next(row for row in events if row["payload"]["alert_id"] == evidence["alert_id"])
    event["payload"]["decision"] = "tampered"
    _write_jsonl(events_path, events)

    report = replay_alert(evidence["alert_id"])

    assert report.passed is False
    assert report.merkle_proof_valid is False


def _build_replay_evidence(tmp_path: Path) -> dict:
    gold_records_path = _build_gold_records(tmp_path)
    promotion_manifest_path = _build_promotion_manifest(tmp_path, gold_records_path)
    scoring = score_gold_features(
        gold_records_path,
        promotion_manifest_path,
        tmp_path / "scoring",
        tmp_path / "governance_events" / "inference_events.jsonl",
        scoring_batch_id="SCORE-REPLAY",
        scored_at=datetime(2026, 1, 6, tzinfo=UTC),
        actor="test_scoring_job",
    )
    batch = build_anchor_batch(
        [scoring.governance_events_path],
        tmp_path / "anchor_batches" / "latest",
        batch_id="BATCH-REPLAY",
        built_at=datetime(2026, 1, 7, tzinfo=UTC),
    )
    _mark_batch_as_anchored(batch.manifest_path, tx_hash="0x" + "d" * 64)
    events = _read_jsonl(scoring.governance_events_path)

    return {
        "gold_records_path": gold_records_path,
        "promotion_manifest_path": promotion_manifest_path,
        "inference_events_path": scoring.governance_events_path,
        "anchor_batches_dir": tmp_path / "anchor_batches",
        "alert_id": events[0]["payload"]["alert_id"],
        "event_count": len(events),
    }


def _build_gold_records(tmp_path: Path) -> Path:
    dataset = generate_synthetic_swift_dataset(8, seed=91, anomaly_rate=0.25)
    raw_paths = dataset.write_jsonl(tmp_path / "raw")
    bronze = ingest_bronze_raw_messages(
        raw_paths["raw_messages"],
        tmp_path / "bronze",
        batch_id="BRONZE-REPLAY",
        ingested_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    silver = parse_validate_silver(
        bronze.records_path,
        tmp_path / "silver",
        tmp_path / "quarantine",
        tmp_path / "governance_events" / "quarantine_events.jsonl",
        validation_batch_id="SILVER-REPLAY",
        validated_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    gold = build_gold_features(
        silver.instructions_path,
        silver.statuses_path,
        tmp_path / "gold",
        gold_snapshot_id="GOLD-REPLAY",
        built_at=datetime(2026, 1, 3, tzinfo=UTC),
    )
    return gold.records_path


def _build_promotion_manifest(tmp_path: Path, gold_records_path: Path) -> Path:
    registry_dir = tmp_path / "registry"
    registry_dir.mkdir(parents=True, exist_ok=True)
    model_path = registry_dir / "model.joblib"

    gold_records = _read_jsonl(gold_records_path)
    frame = pd.DataFrame(gold_records)
    model = Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            (
                "isolation_forest",
                IsolationForest(
                    n_estimators=20,
                    contamination=0.25,
                    random_state=42,
                ),
            ),
        ]
    )
    model.fit(frame[MODEL_FEATURE_COLUMNS].astype(float))
    joblib.dump(model, model_path)

    manifest = {
        "approved": True,
        "promotion_id": "PROMOTE-REPLAY",
        "promotion_manifest_hash": "a" * 64,
        "model_name": "audit_lakehouse_isolation_forest",
        "model_version": "TRAIN-REPLAY",
        "promoted_model_path": str(model_path),
    }
    manifest_path = registry_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def _mark_batch_as_anchored(manifest_path: Path, *, tx_hash: str) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        {
            "anchored": True,
            "tx_hash": tx_hash,
            "block_number": 123,
            "onchain_root": manifest["merkle_root"],
        }
    )
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")


def _set_replay_env(monkeypatch, evidence: dict) -> None:
    monkeypatch.setenv("AUDIT_LAKEHOUSE_GOLD_RECORDS", str(evidence["gold_records_path"]))
    monkeypatch.setenv(
        "AUDIT_LAKEHOUSE_PROMOTION_MANIFEST", str(evidence["promotion_manifest_path"])
    )
    monkeypatch.setenv("AUDIT_LAKEHOUSE_INFERENCE_EVENTS", str(evidence["inference_events_path"]))
    monkeypatch.setenv("AUDIT_LAKEHOUSE_ANCHOR_BATCHES_DIR", str(evidence["anchor_batches_dir"]))


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )
