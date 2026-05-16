"""Tests for Bronze raw-message ingestion."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from audit_lakehouse.generator import generate_synthetic_swift_dataset
from audit_lakehouse.hashing import sha256_hex
from audit_lakehouse.lakehouse import ingest_bronze_raw_messages


def test_ingest_bronze_raw_messages_writes_records_and_manifest(tmp_path) -> None:
    dataset = generate_synthetic_swift_dataset(4, seed=31, anomaly_rate=0.25)
    raw_dir = tmp_path / "raw"
    raw_paths = dataset.write_jsonl(raw_dir)

    result = ingest_bronze_raw_messages(
        raw_paths["raw_messages"],
        tmp_path / "bronze",
        batch_id="BRONZE-TEST",
        ingested_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )

    assert result.records_read == len(dataset.raw_messages)
    assert result.records_written == len(dataset.raw_messages)
    assert result.ingestion_batch_id == "BRONZE-TEST"
    assert result.records_path.exists()
    assert result.manifest_path.exists()

    bronze_rows = [
        json.loads(line) for line in result.records_path.read_text(encoding="utf-8").splitlines()
    ]
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

    assert len(bronze_rows) == len(dataset.raw_messages)
    assert manifest["records_read"] == len(dataset.raw_messages)
    assert manifest["records_written"] == len(dataset.raw_messages)
    assert manifest["schema_version"] == 1
    assert bronze_rows[0]["bronze_record_id"] == "BRONZE-TEST-00000000"
    assert bronze_rows[0]["ingested_at"] == "2026-01-01T12:00:00+00:00"
    assert bronze_rows[0]["source_line_number"] == 1


def test_bronze_raw_payload_hash_is_stable(tmp_path) -> None:
    dataset = generate_synthetic_swift_dataset(1, seed=32, anomaly_rate=0)
    raw_paths = dataset.write_jsonl(tmp_path / "raw")

    result = ingest_bronze_raw_messages(
        raw_paths["raw_messages"],
        tmp_path / "bronze",
        batch_id="BRONZE-HASH",
        ingested_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    bronze_row = json.loads(result.records_path.read_text(encoding="utf-8").splitlines()[0])
    raw_row = dataset.raw_messages[0]

    assert bronze_row["raw_payload_hash"] == sha256_hex(
        {
            "message_id": raw_row["message_id"],
            "message_type": raw_row["message_type"],
            "transaction_reference": raw_row["transaction_reference"],
            "emitted_at": raw_row["emitted_at"].isoformat(),
            "raw_message": raw_row["raw_message"],
        }
    )


def test_ingest_bronze_rejects_missing_input(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        ingest_bronze_raw_messages(tmp_path / "missing.jsonl", tmp_path / "bronze")


def test_ingest_bronze_rejects_naive_ingestion_time(tmp_path) -> None:
    dataset = generate_synthetic_swift_dataset(1, seed=33, anomaly_rate=0)
    raw_paths = dataset.write_jsonl(tmp_path / "raw")

    with pytest.raises(ValueError, match="timezone-aware"):
        ingest_bronze_raw_messages(
            raw_paths["raw_messages"],
            tmp_path / "bronze",
            ingested_at=datetime(2026, 1, 1),
        )


def test_ingest_bronze_rejects_missing_required_fields(tmp_path) -> None:
    raw_path = tmp_path / "raw.jsonl"
    raw_path.write_text(json.dumps({"message_id": "RAW-1"}) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing required fields"):
        ingest_bronze_raw_messages(raw_path, tmp_path / "bronze")


def test_ingest_bronze_rejects_invalid_jsonl(tmp_path) -> None:
    raw_path = tmp_path / "raw.jsonl"
    raw_path.write_text("{not-json}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid JSON"):
        ingest_bronze_raw_messages(raw_path, tmp_path / "bronze")
