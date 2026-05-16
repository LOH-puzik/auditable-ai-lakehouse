"""Gold feature engineering for model-ready settlement-risk rows."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

from swift_audit.generator.mt548 import SettlementStatus
from swift_audit.hashing import sha256_hex

MODEL_FEATURE_COLUMNS = [
    "quantity",
    "settlement_amount",
    "settlement_amount_missing",
    "settlement_value_per_unit",
    "settlement_lag_days",
    "status_count",
    "pending_count",
    "matched_count",
    "unmatched_count",
    "failed_count",
    "settled_count",
    "cancelled_count",
    "reason_code_count",
    "isin_mismatch_count",
    "hours_to_first_status",
    "hours_to_last_status",
    "last_status_pending",
    "last_status_matched",
    "last_status_unmatched",
    "last_status_failed",
    "last_status_settled",
    "last_status_cancelled",
    "last_status_none",
]


@dataclass(frozen=True)
class GoldFeatureResult:
    """File outputs and row counts produced by Gold feature engineering."""

    instructions_path: Path
    statuses_path: Path
    output_dir: Path
    records_path: Path
    manifest_path: Path
    gold_snapshot_id: str
    records_read_instructions: int
    records_read_statuses: int
    features_written: int


def build_gold_features(
    instructions_path: str | Path,
    statuses_path: str | Path,
    output_dir: str | Path,
    *,
    gold_snapshot_id: str | None = None,
    built_at: datetime | None = None,
) -> GoldFeatureResult:
    """Build one model-ready Gold feature row per Silver instruction."""
    instruction_source = Path(instructions_path)
    status_source = Path(statuses_path)
    target_dir = Path(output_dir)
    if not instruction_source.exists():
        raise FileNotFoundError(f"Silver instructions input does not exist: {instruction_source}")
    if not status_source.exists():
        raise FileNotFoundError(f"Silver statuses input does not exist: {status_source}")

    build_time = built_at or datetime.now(UTC)
    if build_time.tzinfo is None:
        raise ValueError("built_at must be timezone-aware")
    build_time = build_time.astimezone(UTC)

    snapshot_id = gold_snapshot_id or f"GOLD-{build_time.strftime('%Y%m%d%H%M%S')}"
    instructions = _read_jsonl(instruction_source)
    statuses = _read_jsonl(status_source)
    statuses_by_reference = _group_statuses_by_reference(statuses)

    feature_rows = [
        _build_feature_row(
            instruction,
            statuses_by_reference.get(str(instruction["transaction_reference"]), []),
            sequence=index,
            gold_snapshot_id=snapshot_id,
            built_at=build_time,
        )
        for index, instruction in enumerate(instructions)
    ]

    target_dir.mkdir(parents=True, exist_ok=True)
    records_path = target_dir / "records.jsonl"
    manifest_path = target_dir / "manifest.json"

    _write_jsonl(records_path, feature_rows)
    manifest = {
        "layer": "gold",
        "dataset": "swift_settlement_features",
        "schema_version": 1,
        "gold_snapshot_id": snapshot_id,
        "built_at": build_time,
        "instructions_path": str(instruction_source),
        "statuses_path": str(status_source),
        "records_path": str(records_path),
        "records_read_instructions": len(instructions),
        "records_read_statuses": len(statuses),
        "features_written": len(feature_rows),
        "feature_columns": MODEL_FEATURE_COLUMNS,
        "feature_manifest_hash": _feature_manifest_hash(feature_rows),
    }
    manifest_path.write_text(
        json.dumps(_json_ready(manifest), indent=2, sort_keys=True),
        encoding="utf-8",
    )

    return GoldFeatureResult(
        instructions_path=instruction_source,
        statuses_path=status_source,
        output_dir=target_dir,
        records_path=records_path,
        manifest_path=manifest_path,
        gold_snapshot_id=snapshot_id,
        records_read_instructions=len(instructions),
        records_read_statuses=len(statuses),
        features_written=len(feature_rows),
    )


def _build_feature_row(
    instruction: dict[str, Any],
    statuses: list[dict[str, Any]],
    *,
    sequence: int,
    gold_snapshot_id: str,
    built_at: datetime,
) -> dict[str, Any]:
    ordered_statuses = sorted(statuses, key=lambda row: _parse_datetime(row["reported_at"]))
    feature_values = _compute_feature_values(instruction, ordered_statuses)
    anomaly_label = _first_non_empty(
        [instruction.get("anomaly_label"), *[status.get("anomaly_label") for status in statuses]]
    )
    feature_row_hash = sha256_hex(
        {
            "transaction_reference": str(instruction["transaction_reference"]),
            "features": feature_values,
        }
    )

    return {
        "gold_record_id": f"{gold_snapshot_id}-{sequence:08d}",
        "gold_snapshot_id": gold_snapshot_id,
        "built_at": built_at,
        "instruction_id": instruction.get("instruction_id"),
        "transaction_reference": instruction["transaction_reference"],
        "isin": instruction["isin"],
        "counterparty_bic": instruction["counterparty_bic"],
        "instruction_silver_record_id": instruction["silver_record_id"],
        "instruction_structured_hash": instruction["structured_hash"],
        "status_silver_record_ids": [status["silver_record_id"] for status in ordered_statuses],
        "status_structured_hashes": [status["structured_hash"] for status in ordered_statuses],
        "feature_columns": MODEL_FEATURE_COLUMNS,
        "feature_row_hash": feature_row_hash,
        "anomaly_label": anomaly_label,
        "is_anomaly": anomaly_label is not None,
        **feature_values,
    }


def _compute_feature_values(
    instruction: dict[str, Any],
    statuses: list[dict[str, Any]],
) -> dict[str, int | float]:
    quantity = float(instruction["quantity"])
    settlement_amount_raw = instruction.get("settlement_amount")
    settlement_amount_missing = int(settlement_amount_raw is None)
    settlement_amount = 0.0 if settlement_amount_raw is None else float(settlement_amount_raw)
    trade_date = _parse_date(instruction["trade_date"])
    settlement_date = _parse_date(instruction["settlement_date"])
    settlement_lag_days = (settlement_date - trade_date).days

    status_counter = Counter(str(status["status"]) for status in statuses)
    last_status = str(statuses[-1]["status"]) if statuses else "NONE"
    first_reported_at = _parse_datetime(statuses[0]["reported_at"]) if statuses else None
    last_reported_at = _parse_datetime(statuses[-1]["reported_at"]) if statuses else None
    trade_start = datetime.combine(trade_date, time.min, tzinfo=UTC)
    isin = str(instruction["isin"])

    return {
        "quantity": round(quantity, 6),
        "settlement_amount": round(settlement_amount, 6),
        "settlement_amount_missing": settlement_amount_missing,
        "settlement_value_per_unit": (
            round(settlement_amount / quantity, 6) if quantity > 0 else 0.0
        ),
        "settlement_lag_days": settlement_lag_days,
        "status_count": len(statuses),
        "pending_count": status_counter[SettlementStatus.PENDING.value],
        "matched_count": status_counter[SettlementStatus.MATCHED.value],
        "unmatched_count": status_counter[SettlementStatus.UNMATCHED.value],
        "failed_count": status_counter[SettlementStatus.FAILED.value],
        "settled_count": status_counter[SettlementStatus.SETTLED.value],
        "cancelled_count": status_counter[SettlementStatus.CANCELLED.value],
        "reason_code_count": sum(1 for status in statuses if status.get("reason_code")),
        "isin_mismatch_count": sum(1 for status in statuses if status.get("isin") != isin),
        "hours_to_first_status": _hours_between(trade_start, first_reported_at),
        "hours_to_last_status": _hours_between(trade_start, last_reported_at),
        "last_status_pending": int(last_status == SettlementStatus.PENDING.value),
        "last_status_matched": int(last_status == SettlementStatus.MATCHED.value),
        "last_status_unmatched": int(last_status == SettlementStatus.UNMATCHED.value),
        "last_status_failed": int(last_status == SettlementStatus.FAILED.value),
        "last_status_settled": int(last_status == SettlementStatus.SETTLED.value),
        "last_status_cancelled": int(last_status == SettlementStatus.CANCELLED.value),
        "last_status_none": int(last_status == "NONE"),
    }


def _group_statuses_by_reference(statuses: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for status in statuses:
        grouped[str(status["transaction_reference"])].append(status)
    return dict(grouped)


def _feature_manifest_hash(records: list[dict[str, Any]]) -> str:
    return sha256_hex(
        {
            "feature_row_hashes": [record["feature_row_hash"] for record in records],
            "feature_columns": MODEL_FEATURE_COLUMNS,
        }
    )


def _first_non_empty(values: list[Any]) -> str | None:
    for value in values:
        if value is not None:
            return str(value)
    return None


def _hours_between(start: datetime, end: datetime | None) -> float:
    if end is None:
        return 0.0
    return round((end.astimezone(UTC) - start.astimezone(UTC)).total_seconds() / 3600, 6)


def _parse_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return date.fromisoformat(str(value))


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


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
