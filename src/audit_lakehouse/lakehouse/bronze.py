"""Bronze ingestion for raw synthetic SWIFT messages."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from audit_lakehouse.hashing import sha256_hex

REQUIRED_RAW_MESSAGE_FIELDS = {
    "message_id",
    "message_type",
    "transaction_reference",
    "emitted_at",
    "raw_message",
    "source_system",
}


@dataclass(frozen=True)
class BronzeIngestionResult:
    """File outputs and row counts produced by a Bronze ingestion run."""

    input_path: Path
    output_dir: Path
    records_path: Path
    manifest_path: Path
    ingestion_batch_id: str
    records_read: int
    records_written: int


def ingest_bronze_raw_messages(
    input_path: str | Path,
    output_dir: str | Path,
    *,
    batch_id: str | None = None,
    ingested_at: datetime | None = None,
) -> BronzeIngestionResult:
    """Read raw-message JSONL, enrich it with ingestion metadata, and write Bronze JSONL."""
    source_path = Path(input_path)
    target_dir = Path(output_dir)
    if not source_path.exists():
        raise FileNotFoundError(f"Raw message input does not exist: {source_path}")

    ingestion_time = ingested_at or datetime.now(UTC)
    if ingestion_time.tzinfo is None:
        raise ValueError("ingested_at must be timezone-aware")
    ingestion_time = ingestion_time.astimezone(UTC)

    ingestion_batch_id = batch_id or f"BRONZE-{ingestion_time.strftime('%Y%m%d%H%M%S')}"
    raw_records = _read_jsonl(source_path)
    bronze_records = [
        _to_bronze_record(
            record,
            source_path=source_path,
            source_line_number=index + 1,
            sequence=index,
            ingestion_batch_id=ingestion_batch_id,
            ingested_at=ingestion_time,
        )
        for index, record in enumerate(raw_records)
    ]

    target_dir.mkdir(parents=True, exist_ok=True)
    records_path = target_dir / "records.jsonl"
    manifest_path = target_dir / "manifest.json"

    _write_jsonl(records_path, bronze_records)
    manifest = {
        "layer": "bronze",
        "dataset": "swift_raw_messages",
        "schema_version": 1,
        "ingestion_batch_id": ingestion_batch_id,
        "ingested_at": ingestion_time,
        "input_path": str(source_path),
        "records_path": str(records_path),
        "records_read": len(raw_records),
        "records_written": len(bronze_records),
        "required_raw_fields": sorted(REQUIRED_RAW_MESSAGE_FIELDS),
    }
    manifest_path.write_text(
        json.dumps(_json_ready(manifest), indent=2, sort_keys=True),
        encoding="utf-8",
    )

    return BronzeIngestionResult(
        input_path=source_path,
        output_dir=target_dir,
        records_path=records_path,
        manifest_path=manifest_path,
        ingestion_batch_id=ingestion_batch_id,
        records_read=len(raw_records),
        records_written=len(bronze_records),
    )


def _to_bronze_record(
    record: dict[str, Any],
    *,
    source_path: Path,
    source_line_number: int,
    sequence: int,
    ingestion_batch_id: str,
    ingested_at: datetime,
) -> dict[str, Any]:
    missing = REQUIRED_RAW_MESSAGE_FIELDS - record.keys()
    if missing:
        missing_fields = ", ".join(sorted(missing))
        raise ValueError(f"Raw message record is missing required fields: {missing_fields}")

    raw_payload_hash = sha256_hex(
        {
            "message_id": str(record["message_id"]),
            "message_type": str(record["message_type"]),
            "transaction_reference": str(record["transaction_reference"]),
            "emitted_at": str(record["emitted_at"]),
            "raw_message": str(record["raw_message"]),
        }
    )

    return {
        "bronze_record_id": f"{ingestion_batch_id}-{sequence:08d}",
        "ingestion_batch_id": ingestion_batch_id,
        "ingested_at": ingested_at,
        "source_file": str(source_path),
        "source_line_number": source_line_number,
        "source_message_id": record["message_id"],
        "message_type": record["message_type"],
        "instruction_id": record.get("instruction_id"),
        "transaction_reference": record["transaction_reference"],
        "emitted_at": record["emitted_at"],
        "raw_message": record["raw_message"],
        "raw_payload_hash": raw_payload_hash,
        "anomaly_label": record.get("anomaly_label"),
        "source_system": record["source_system"],
    }


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
