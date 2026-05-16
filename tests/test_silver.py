"""Tests for Silver parsing, validation, and quarantine handling."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from audit_lakehouse.generator import generate_synthetic_swift_dataset
from audit_lakehouse.lakehouse import ingest_bronze_raw_messages, parse_validate_silver


def test_parse_validate_silver_writes_instruction_and_status_tables(tmp_path) -> None:
    bronze_path = _build_bronze_records(tmp_path, n=3, seed=41)

    result = parse_validate_silver(
        bronze_path,
        tmp_path / "silver",
        tmp_path / "quarantine",
        tmp_path / "events" / "quarantine_events.jsonl",
        validation_batch_id="SILVER-TEST",
        validated_at=datetime(2026, 1, 2, 12, 0, tzinfo=UTC),
    )

    instructions = _read_jsonl(result.instructions_path)
    statuses = _read_jsonl(result.statuses_path)
    quarantine = _read_jsonl(result.quarantine_path)
    events = _read_jsonl(result.governance_events_path)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

    assert result.records_read == 12
    assert result.instructions_written == 3
    assert result.statuses_written == 9
    assert result.quarantined == 0
    assert len(instructions) == 3
    assert len(statuses) == 9
    assert quarantine == []
    assert events == []
    assert manifest["validation_batch_id"] == "SILVER-TEST"
    assert instructions[0]["message_type"] == "MT540"
    assert statuses[0]["message_type"] == "MT548"
    assert len(instructions[0]["structured_hash"]) == 64
    assert instructions[0]["validated_at"] == "2026-01-02T12:00:00+00:00"


def test_parse_validate_silver_quarantines_invalid_mt540(tmp_path) -> None:
    bronze_path = _build_bronze_records(tmp_path, n=1, seed=42)
    _rewrite_first_bronze_raw_message(
        bronze_path,
        lambda raw_message: raw_message.replace(":35B:ISIN ", ":35B:BROKEN ", 1),
    )

    result = parse_validate_silver(
        bronze_path,
        tmp_path / "silver",
        tmp_path / "quarantine",
        tmp_path / "events" / "quarantine_events.jsonl",
        validation_batch_id="SILVER-BAD",
        validated_at=datetime(2026, 1, 2, tzinfo=UTC),
    )

    quarantine = _read_jsonl(result.quarantine_path)
    events = _read_jsonl(result.governance_events_path)

    assert result.quarantined == 1
    assert result.instructions_written == 0
    assert result.statuses_written == 3
    assert quarantine[0]["error_code"] == "UNKNOWN_FIELD"
    assert quarantine[0]["quarantine_record_id"] == "SILVER-BAD-Q-00000000"
    assert events[0]["event_type"] == "quarantine"
    assert len(events[0]["event_hash"]) == 64
    assert events[0]["payload"]["error_code"] == "UNKNOWN_FIELD"


def test_parse_validate_silver_quarantines_invalid_mt548_status(tmp_path) -> None:
    bronze_path = _build_bronze_records(tmp_path, n=1, seed=43)
    _rewrite_first_status_raw_message(
        bronze_path,
        lambda raw_message: raw_message.replace(":25D::IPRC//PENF", ":25D::IPRC//BAD", 1),
    )

    result = parse_validate_silver(
        bronze_path,
        tmp_path / "silver",
        tmp_path / "quarantine",
        tmp_path / "events" / "quarantine_events.jsonl",
        validation_batch_id="SILVER-BAD-STATUS",
        validated_at=datetime(2026, 1, 2, tzinfo=UTC),
    )

    quarantine = _read_jsonl(result.quarantine_path)

    assert result.instructions_written == 1
    assert result.statuses_written == 2
    assert result.quarantined == 1
    assert quarantine[0]["error_code"] == "INVALID_STATUS"


def test_parse_validate_silver_rejects_missing_input(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        parse_validate_silver(
            tmp_path / "missing.jsonl",
            tmp_path / "silver",
            tmp_path / "quarantine",
            tmp_path / "events.jsonl",
        )


def test_parse_validate_silver_rejects_naive_validation_time(tmp_path) -> None:
    bronze_path = _build_bronze_records(tmp_path, n=1, seed=44)

    with pytest.raises(ValueError, match="timezone-aware"):
        parse_validate_silver(
            bronze_path,
            tmp_path / "silver",
            tmp_path / "quarantine",
            tmp_path / "events.jsonl",
            validated_at=datetime(2026, 1, 2),
        )


def _build_bronze_records(tmp_path: Path, *, n: int, seed: int) -> Path:
    dataset = generate_synthetic_swift_dataset(n, seed=seed, anomaly_rate=0)
    raw_paths = dataset.write_jsonl(tmp_path / "raw")
    bronze = ingest_bronze_raw_messages(
        raw_paths["raw_messages"],
        tmp_path / "bronze",
        batch_id=f"BRONZE-{seed}",
        ingested_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    return bronze.records_path


def _rewrite_first_bronze_raw_message(bronze_path: Path, rewrite) -> None:
    rows = _read_jsonl(bronze_path)
    rows[0]["raw_message"] = rewrite(rows[0]["raw_message"])
    _write_jsonl(bronze_path, rows)


def _rewrite_first_status_raw_message(bronze_path: Path, rewrite) -> None:
    rows = _read_jsonl(bronze_path)
    for row in rows:
        if row["message_type"] == "MT548":
            row["raw_message"] = rewrite(row["raw_message"])
            break
    _write_jsonl(bronze_path, rows)


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )
