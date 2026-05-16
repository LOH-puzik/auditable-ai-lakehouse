"""Tests for Gold feature engineering."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from audit_lakehouse.generator import AnomalyFamily, generate_synthetic_swift_dataset
from audit_lakehouse.lakehouse import (
    build_gold_features,
    ingest_bronze_raw_messages,
    parse_validate_silver,
)


def test_build_gold_features_writes_model_ready_rows(tmp_path) -> None:
    silver = _build_silver_outputs(tmp_path, n=3, seed=51)

    result = build_gold_features(
        silver.instructions_path,
        silver.statuses_path,
        tmp_path / "gold",
        gold_snapshot_id="GOLD-TEST",
        built_at=datetime(2026, 1, 3, 12, 0, tzinfo=UTC),
    )

    rows = _read_jsonl(result.records_path)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

    assert result.records_read_instructions == 3
    assert result.records_read_statuses == 9
    assert result.features_written == 3
    assert len(rows) == 3
    assert manifest["gold_snapshot_id"] == "GOLD-TEST"
    assert manifest["features_written"] == 3
    assert len(manifest["feature_manifest_hash"]) == 64
    assert rows[0]["gold_record_id"] == "GOLD-TEST-00000000"
    assert rows[0]["status_count"] == 3
    assert rows[0]["settled_count"] == 1
    assert rows[0]["last_status_settled"] == 1
    assert rows[0]["last_status_none"] == 0
    assert len(rows[0]["feature_row_hash"]) == 64
    assert len(rows[0]["instruction_structured_hash"]) == 64
    assert len(rows[0]["status_structured_hashes"]) == 3


def test_build_gold_features_handles_missing_status_history(tmp_path) -> None:
    silver = _build_silver_outputs(tmp_path, n=1, seed=52)
    empty_statuses = tmp_path / "empty_statuses.jsonl"
    empty_statuses.write_text("", encoding="utf-8")

    result = build_gold_features(
        silver.instructions_path,
        empty_statuses,
        tmp_path / "gold",
        gold_snapshot_id="GOLD-NO-STATUS",
        built_at=datetime(2026, 1, 3, tzinfo=UTC),
    )

    row = _read_jsonl(result.records_path)[0]

    assert result.records_read_statuses == 0
    assert row["status_count"] == 0
    assert row["hours_to_first_status"] == 0.0
    assert row["last_status_none"] == 1
    assert row["status_silver_record_ids"] == []


def test_build_gold_features_counts_isin_mismatch_anomaly(tmp_path) -> None:
    silver = _build_silver_outputs(
        tmp_path,
        n=2,
        seed=53,
        anomaly_rate=1,
        anomaly_families=[AnomalyFamily.MISMATCHED_ISIN],
    )

    result = build_gold_features(
        silver.instructions_path,
        silver.statuses_path,
        tmp_path / "gold",
        gold_snapshot_id="GOLD-MISMATCH",
        built_at=datetime(2026, 1, 3, tzinfo=UTC),
    )

    rows = _read_jsonl(result.records_path)

    assert all(row["is_anomaly"] is True for row in rows)
    assert all(row["anomaly_label"] == AnomalyFamily.MISMATCHED_ISIN.value for row in rows)
    assert all(row["isin_mismatch_count"] == 3 for row in rows)


def test_build_gold_feature_hash_is_stable_across_snapshots(tmp_path) -> None:
    silver = _build_silver_outputs(tmp_path, n=1, seed=54)

    first = build_gold_features(
        silver.instructions_path,
        silver.statuses_path,
        tmp_path / "gold_1",
        gold_snapshot_id="GOLD-1",
        built_at=datetime(2026, 1, 3, tzinfo=UTC),
    )
    second = build_gold_features(
        silver.instructions_path,
        silver.statuses_path,
        tmp_path / "gold_2",
        gold_snapshot_id="GOLD-2",
        built_at=datetime(2026, 1, 4, tzinfo=UTC),
    )

    first_row = _read_jsonl(first.records_path)[0]
    second_row = _read_jsonl(second.records_path)[0]

    assert first_row["feature_row_hash"] == second_row["feature_row_hash"]
    assert first_row["gold_record_id"] != second_row["gold_record_id"]


def test_build_gold_features_rejects_missing_input(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        build_gold_features(
            tmp_path / "missing_instructions.jsonl",
            tmp_path / "missing_statuses.jsonl",
            tmp_path / "gold",
        )


def test_build_gold_features_rejects_naive_build_time(tmp_path) -> None:
    silver = _build_silver_outputs(tmp_path, n=1, seed=55)

    with pytest.raises(ValueError, match="timezone-aware"):
        build_gold_features(
            silver.instructions_path,
            silver.statuses_path,
            tmp_path / "gold",
            built_at=datetime(2026, 1, 3),
        )


def _build_silver_outputs(
    tmp_path: Path,
    *,
    n: int,
    seed: int,
    anomaly_rate: float = 0,
    anomaly_families: list[AnomalyFamily] | None = None,
):
    dataset = generate_synthetic_swift_dataset(
        n,
        seed=seed,
        anomaly_rate=anomaly_rate,
        anomaly_families=anomaly_families,
    )
    raw_paths = dataset.write_jsonl(tmp_path / f"raw_{seed}")
    bronze = ingest_bronze_raw_messages(
        raw_paths["raw_messages"],
        tmp_path / f"bronze_{seed}",
        batch_id=f"BRONZE-{seed}",
        ingested_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    return parse_validate_silver(
        bronze.records_path,
        tmp_path / f"silver_{seed}",
        tmp_path / f"quarantine_{seed}",
        tmp_path / f"events_{seed}" / "quarantine_events.jsonl",
        validation_batch_id=f"SILVER-{seed}",
        validated_at=datetime(2026, 1, 2, tzinfo=UTC),
    )


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
