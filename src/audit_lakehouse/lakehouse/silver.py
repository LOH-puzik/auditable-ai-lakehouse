"""Silver parsing, structural validation, and quarantine handling."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from audit_lakehouse.events import QuarantineEvent
from audit_lakehouse.generator.mt548 import SettlementStatus
from audit_lakehouse.hashing import sha256_hex

_ISIN_PATTERN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
_BIC_PATTERN = re.compile(r"^[A-Z0-9]{8}([A-Z0-9]{3})?$")
_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")


@dataclass(frozen=True)
class SilverValidationResult:
    """File outputs and row counts produced by Silver parsing and validation."""

    input_path: Path
    silver_output_dir: Path
    quarantine_output_dir: Path
    governance_events_path: Path
    instructions_path: Path
    statuses_path: Path
    quarantine_path: Path
    manifest_path: Path
    validation_batch_id: str
    records_read: int
    instructions_written: int
    statuses_written: int
    quarantined: int
    quarantine_events_written: int


class SilverValidationError(ValueError):
    """An expected parse/validation failure that should send a row to quarantine."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def parse_validate_silver(
    bronze_records_path: str | Path,
    silver_output_dir: str | Path,
    quarantine_output_dir: str | Path,
    governance_events_path: str | Path,
    *,
    validation_batch_id: str | None = None,
    validated_at: datetime | None = None,
    actor: str = "silver_validation_job",
) -> SilverValidationResult:
    """Parse Bronze raw messages into Silver tables and quarantine invalid records."""
    source_path = Path(bronze_records_path)
    if not source_path.exists():
        raise FileNotFoundError(f"Bronze records input does not exist: {source_path}")

    validation_time = validated_at or datetime.now(UTC)
    if validation_time.tzinfo is None:
        raise ValueError("validated_at must be timezone-aware")
    validation_time = validation_time.astimezone(UTC)

    batch_id = validation_batch_id or f"SILVER-{validation_time.strftime('%Y%m%d%H%M%S')}"
    bronze_records = _read_jsonl(source_path)

    instructions: list[dict[str, Any]] = []
    statuses: list[dict[str, Any]] = []
    quarantine_records: list[dict[str, Any]] = []
    quarantine_events: list[dict[str, Any]] = []

    for sequence, bronze_record in enumerate(bronze_records):
        try:
            parsed = _parse_bronze_record(
                bronze_record,
                sequence=sequence,
                validation_batch_id=batch_id,
                validated_at=validation_time,
            )
        except SilverValidationError as exc:
            quarantine_record = _build_quarantine_record(
                bronze_record,
                sequence=sequence,
                validation_batch_id=batch_id,
                validated_at=validation_time,
                error_code=exc.code,
                error_message=str(exc),
            )
            quarantine_records.append(quarantine_record)
            quarantine_events.append(_build_quarantine_event(quarantine_record, actor=actor))
            continue

        if parsed["message_type"] == "MT540":
            instructions.append(parsed)
        elif parsed["message_type"] == "MT548":
            statuses.append(parsed)
        else:
            raise AssertionError(f"Unexpected parsed message type: {parsed['message_type']}")

    silver_dir = Path(silver_output_dir)
    quarantine_dir = Path(quarantine_output_dir)
    events_path = Path(governance_events_path)

    silver_dir.mkdir(parents=True, exist_ok=True)
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    events_path.parent.mkdir(parents=True, exist_ok=True)

    instructions_path = silver_dir / "instructions.jsonl"
    statuses_path = silver_dir / "statuses.jsonl"
    quarantine_path = quarantine_dir / "records.jsonl"
    manifest_path = silver_dir / "manifest.json"

    _write_jsonl(instructions_path, instructions)
    _write_jsonl(statuses_path, statuses)
    _write_jsonl(quarantine_path, quarantine_records)
    _write_jsonl(events_path, quarantine_events)

    manifest = {
        "layer": "silver",
        "dataset": "swift_messages",
        "schema_version": 1,
        "validation_batch_id": batch_id,
        "validated_at": validation_time,
        "input_path": str(source_path),
        "instructions_path": str(instructions_path),
        "statuses_path": str(statuses_path),
        "quarantine_path": str(quarantine_path),
        "governance_events_path": str(events_path),
        "records_read": len(bronze_records),
        "instructions_written": len(instructions),
        "statuses_written": len(statuses),
        "quarantined": len(quarantine_records),
        "quarantine_events_written": len(quarantine_events),
    }
    manifest_path.write_text(
        json.dumps(_json_ready(manifest), indent=2, sort_keys=True),
        encoding="utf-8",
    )

    return SilverValidationResult(
        input_path=source_path,
        silver_output_dir=silver_dir,
        quarantine_output_dir=quarantine_dir,
        governance_events_path=events_path,
        instructions_path=instructions_path,
        statuses_path=statuses_path,
        quarantine_path=quarantine_path,
        manifest_path=manifest_path,
        validation_batch_id=batch_id,
        records_read=len(bronze_records),
        instructions_written=len(instructions),
        statuses_written=len(statuses),
        quarantined=len(quarantine_records),
        quarantine_events_written=len(quarantine_events),
    )


def _parse_bronze_record(
    bronze_record: dict[str, Any],
    *,
    sequence: int,
    validation_batch_id: str,
    validated_at: datetime,
) -> dict[str, Any]:
    message_type = str(bronze_record.get("message_type", ""))
    if message_type == "MT540":
        parsed = _parse_mt540(str(bronze_record.get("raw_message", "")))
    elif message_type == "MT548":
        parsed = _parse_mt548(str(bronze_record.get("raw_message", "")))
    else:
        raise SilverValidationError(
            "UNSUPPORTED_MESSAGE_TYPE",
            f"Unsupported message_type {message_type!r}",
        )

    parsed_reference = parsed["transaction_reference"]
    bronze_reference = str(bronze_record.get("transaction_reference", ""))
    if parsed_reference != bronze_reference:
        raise SilverValidationError(
            "REFERENCE_MISMATCH",
            (
                "Parsed transaction reference does not match Bronze metadata: "
                f"{parsed_reference!r} != {bronze_reference!r}"
            ),
        )

    parsed["silver_record_id"] = f"{validation_batch_id}-{sequence:08d}"
    parsed["bronze_record_id"] = bronze_record.get("bronze_record_id")
    parsed["instruction_id"] = bronze_record.get("instruction_id")
    parsed["source_message_id"] = bronze_record.get("source_message_id")
    parsed["ingestion_batch_id"] = bronze_record.get("ingestion_batch_id")
    parsed["validation_batch_id"] = validation_batch_id
    parsed["validated_at"] = validated_at
    parsed["raw_payload_hash"] = bronze_record.get("raw_payload_hash")
    parsed["anomaly_label"] = bronze_record.get("anomaly_label")
    parsed["structured_hash"] = _structured_hash(parsed)
    return parsed


def _parse_mt540(raw_message: str) -> dict[str, Any]:
    fields = _extract_fields(raw_message)
    reference = _require_field(fields, "20C::SEME//")
    isin = _require_field(fields, "35B:ISIN ")
    quantity_text = _require_field(fields, "36B::SETT//UNIT/")
    trade_date_text = _require_field(fields, "98A::TRAD//")
    settlement_date_text = _require_field(fields, "98A::SETT//")
    counterparty_bic = _require_field(fields, "95P::DEAG//")
    safekeeping_account = _require_field(fields, "97A::SAFE//")
    settlement_text = fields.get("19A::SETT//")

    _validate_reference(reference)
    _validate_isin(isin)
    quantity = _parse_positive_float(quantity_text, "quantity")
    trade_date = _parse_date(trade_date_text, "trade_date")
    settlement_date = _parse_date(settlement_date_text, "settlement_date")
    if settlement_date < trade_date:
        raise SilverValidationError(
            "INVALID_SETTLEMENT_DATE",
            "settlement_date must be on or after trade_date",
        )
    if not _BIC_PATTERN.match(counterparty_bic):
        raise SilverValidationError("INVALID_BIC", f"Invalid counterparty BIC: {counterparty_bic}")
    if not safekeeping_account:
        raise SilverValidationError("MISSING_SAFEKEEPING_ACCOUNT", "Missing safekeeping account")

    currency = None
    settlement_amount = None
    if settlement_text:
        currency = settlement_text[:3]
        amount_text = settlement_text[3:]
        if not _CURRENCY_PATTERN.match(currency):
            raise SilverValidationError("INVALID_CURRENCY", f"Invalid currency: {currency}")
        settlement_amount = _parse_positive_float(amount_text, "settlement_amount")

    return {
        "message_type": "MT540",
        "transaction_reference": reference,
        "isin": isin,
        "quantity": quantity,
        "trade_date": trade_date,
        "settlement_date": settlement_date,
        "counterparty_bic": counterparty_bic,
        "safekeeping_account": safekeeping_account,
        "settlement_amount": settlement_amount,
        "currency": currency,
    }


def _parse_mt548(raw_message: str) -> dict[str, Any]:
    fields = _extract_fields(raw_message)
    reference = _require_field(fields, "20C::RELA//")
    isin = _require_field(fields, "35B:ISIN ")
    status = _require_field(fields, "25D::IPRC//")
    reported_at_text = _require_field(fields, "98C::STAT//")
    reason_code = fields.get("24B::REAS//")

    _validate_reference(reference)
    _validate_isin(isin)
    if status not in {item.value for item in SettlementStatus}:
        raise SilverValidationError("INVALID_STATUS", f"Invalid settlement status: {status}")
    reported_at = _parse_datetime(reported_at_text, "reported_at")

    return {
        "message_type": "MT548",
        "transaction_reference": reference,
        "isin": isin,
        "status": status,
        "reason_code": reason_code,
        "reported_at": reported_at,
    }


def _extract_fields(raw_message: str) -> dict[str, str]:
    if not raw_message.strip():
        raise SilverValidationError("EMPTY_MESSAGE", "Raw message is empty")

    fields: dict[str, str] = {}
    for line in raw_message.splitlines():
        stripped = line.strip()
        if not stripped.startswith(":"):
            continue
        key, value = _split_field(stripped[1:])
        fields[key] = value
    return fields


def _split_field(field: str) -> tuple[str, str]:
    known_prefixes = [
        "20C::SEME//",
        "20C::RELA//",
        "35B:ISIN ",
        "36B::SETT//UNIT/",
        "98A::TRAD//",
        "98A::SETT//",
        "95P::DEAG//",
        "97A::SAFE//",
        "19A::SETT//",
        "25D::IPRC//",
        "98C::STAT//",
        "24B::REAS//",
    ]
    for prefix in known_prefixes:
        if field.startswith(prefix):
            return prefix, field[len(prefix) :].strip()
    raise SilverValidationError("UNKNOWN_FIELD", f"Unknown SWIFT field: {field}")


def _require_field(fields: dict[str, str], key: str) -> str:
    value = fields.get(key)
    if value is None or value == "":
        raise SilverValidationError("MISSING_REQUIRED_FIELD", f"Missing required field {key}")
    return value


def _validate_reference(reference: str) -> None:
    if not reference:
        raise SilverValidationError("MISSING_REFERENCE", "Missing transaction reference")


def _validate_isin(isin: str) -> None:
    if not _ISIN_PATTERN.match(isin):
        raise SilverValidationError("INVALID_ISIN", f"Invalid ISIN: {isin}")


def _parse_positive_float(value: str, field_name: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise SilverValidationError(
            "INVALID_NUMBER",
            f"Invalid numeric value for {field_name}: {value}",
        ) from exc
    if parsed <= 0:
        raise SilverValidationError(
            "INVALID_NUMBER",
            f"{field_name} must be positive",
        )
    return parsed


def _parse_date(value: str, field_name: str) -> date:
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError as exc:
        raise SilverValidationError("INVALID_DATE", f"Invalid {field_name}: {value}") from exc


def _parse_datetime(value: str, field_name: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    except ValueError as exc:
        raise SilverValidationError("INVALID_DATETIME", f"Invalid {field_name}: {value}") from exc


def _structured_hash(record: dict[str, Any]) -> str:
    hashable = {
        key: _hashable_value(value)
        for key, value in record.items()
        if key
        in {
            "message_type",
            "transaction_reference",
            "isin",
            "quantity",
            "trade_date",
            "settlement_date",
            "counterparty_bic",
            "safekeeping_account",
            "settlement_amount",
            "currency",
            "status",
            "reason_code",
            "reported_at",
        }
    }
    return sha256_hex(hashable)


def _hashable_value(value: Any) -> Any:
    if value is None:
        return "__NULL__"
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    return value


def _build_quarantine_record(
    bronze_record: dict[str, Any],
    *,
    sequence: int,
    validation_batch_id: str,
    validated_at: datetime,
    error_code: str,
    error_message: str,
) -> dict[str, Any]:
    return {
        "quarantine_record_id": f"{validation_batch_id}-Q-{sequence:08d}",
        "validation_batch_id": validation_batch_id,
        "validated_at": validated_at,
        "bronze_record_id": bronze_record.get("bronze_record_id", ""),
        "source_message_id": bronze_record.get("source_message_id", ""),
        "message_type": bronze_record.get("message_type", ""),
        "transaction_reference": bronze_record.get("transaction_reference", ""),
        "raw_payload_hash": bronze_record.get("raw_payload_hash", ""),
        "error_code": error_code,
        "error_message": error_message,
        "raw_message": bronze_record.get("raw_message", ""),
        "anomaly_label": bronze_record.get("anomaly_label"),
    }


def _build_quarantine_event(record: dict[str, Any], *, actor: str) -> dict[str, Any]:
    payload = {
        "quarantine_record_id": str(record["quarantine_record_id"]),
        "bronze_record_id": str(record["bronze_record_id"]),
        "source_message_id": str(record["source_message_id"]),
        "message_type": str(record["message_type"]),
        "transaction_reference": str(record["transaction_reference"]),
        "raw_payload_hash": str(record["raw_payload_hash"]),
        "error_code": str(record["error_code"]),
        "error_message": str(record["error_message"]),
    }
    event = QuarantineEvent(actor=actor, payload=payload)
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
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    return value
