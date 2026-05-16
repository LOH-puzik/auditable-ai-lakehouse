"""Build file-oriented synthetic SWIFT datasets for the pipeline notebooks."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time
from enum import StrEnum
from pathlib import Path
from typing import Any

from swift_audit.generator.anomalies import AnomalyFamily, inject_anomalies
from swift_audit.generator.mt540 import generate_mt540
from swift_audit.generator.mt548 import SettlementStatus, generate_mt548_chain


@dataclass(frozen=True)
class SyntheticSwiftDataset:
    """Synthetic instruction, status, raw-message, and manifest records."""

    instructions: list[dict[str, Any]]
    statuses: list[dict[str, Any]]
    raw_messages: list[dict[str, Any]]
    manifest: dict[str, Any]

    def write_jsonl(self, output_dir: str | Path) -> dict[str, Path]:
        """Write the dataset as JSONL files plus a JSON manifest."""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        paths = {
            "instructions": output_path / "instructions.jsonl",
            "statuses": output_path / "statuses.jsonl",
            "raw_messages": output_path / "raw_messages.jsonl",
            "manifest": output_path / "manifest.json",
        }
        _write_jsonl(paths["instructions"], self.instructions)
        _write_jsonl(paths["statuses"], self.statuses)
        _write_jsonl(paths["raw_messages"], self.raw_messages)
        paths["manifest"].write_text(
            json.dumps(_json_ready(self.manifest), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return paths


def generate_synthetic_swift_dataset(
    n: int,
    *,
    seed: int = 42,
    anomaly_rate: float = 0.02,
    anomaly_families: list[AnomalyFamily] | None = None,
) -> SyntheticSwiftDataset:
    """Generate labelled MT540/MT548 records and raw SWIFT-like messages."""
    mt540_records = [asdict(message) for message in generate_mt540(n, seed=seed)]
    instructions = inject_anomalies(
        mt540_records,
        rate=anomaly_rate,
        families=anomaly_families,
        seed=seed,
    )

    for index, instruction in enumerate(instructions):
        instruction["instruction_id"] = f"INS-{seed % 10_000:04d}-{index:08d}"
        instruction["source_system"] = "synthetic_swift_generator"

    statuses = _build_status_records(instructions, seed=seed)
    raw_messages = _build_raw_messages(instructions, statuses)
    anomaly_counts = _count_anomalies(instructions)

    manifest = {
        "dataset_name": "synthetic_swift_mt540_mt548",
        "generated_at": datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
        "seed": seed,
        "instruction_count": len(instructions),
        "status_count": len(statuses),
        "raw_message_count": len(raw_messages),
        "anomaly_rate": anomaly_rate,
        "anomaly_families": [family.value for family in (anomaly_families or list(AnomalyFamily))],
        "anomaly_counts": anomaly_counts,
        "files": {
            "instructions": "instructions.jsonl",
            "statuses": "statuses.jsonl",
            "raw_messages": "raw_messages.jsonl",
        },
    }

    return SyntheticSwiftDataset(
        instructions=instructions,
        statuses=statuses,
        raw_messages=raw_messages,
        manifest=manifest,
    )


def _build_status_records(instructions: list[dict[str, Any]], *, seed: int) -> list[dict[str, Any]]:
    statuses: list[dict[str, Any]] = []

    for instruction_index, instruction in enumerate(instructions):
        if instruction.get("anomaly_label") == AnomalyFamily.LATE_SETTLEMENT.value:
            chain = [
                {
                    "transaction_reference": instruction["transaction_reference"],
                    "status": SettlementStatus.PENDING.value,
                    "reason_code": "LATE",
                    "reported_at": instruction["reported_at"],
                }
            ]
        else:
            chain = [
                asdict(message)
                for message in generate_mt548_chain(
                    str(instruction["transaction_reference"]),
                    seed=seed + instruction_index,
                )
            ]

        status_isin = instruction.get("mt548_isin", instruction["isin"])
        for sequence, status in enumerate(chain):
            statuses.append(
                {
                    "status_id": (
                        f"STS-{seed % 10_000:04d}-{instruction_index:08d}-{sequence:02d}"
                    ),
                    "instruction_id": instruction["instruction_id"],
                    "transaction_reference": status["transaction_reference"],
                    "isin": status_isin,
                    "status": _enum_value(status["status"]),
                    "reason_code": status["reason_code"],
                    "reported_at": status["reported_at"],
                    "sequence": sequence,
                    "anomaly_label": instruction["anomaly_label"],
                    "source_system": "synthetic_swift_generator",
                }
            )

    return statuses


def _build_raw_messages(
    instructions: list[dict[str, Any]],
    statuses: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    raw_messages: list[dict[str, Any]] = []

    for instruction in instructions:
        raw_messages.append(
            {
                "message_id": f"RAW-MT540-{instruction['instruction_id']}",
                "message_type": "MT540",
                "instruction_id": instruction["instruction_id"],
                "transaction_reference": instruction["transaction_reference"],
                "emitted_at": _date_at_time(instruction["trade_date"], hour=8),
                "raw_message": _serialize_mt540(instruction),
                "anomaly_label": instruction["anomaly_label"],
                "source_system": "synthetic_swift_generator",
            }
        )

    for status in statuses:
        raw_messages.append(
            {
                "message_id": f"RAW-MT548-{status['status_id']}",
                "message_type": "MT548",
                "instruction_id": status["instruction_id"],
                "transaction_reference": status["transaction_reference"],
                "emitted_at": status["reported_at"],
                "raw_message": _serialize_mt548(status),
                "anomaly_label": status["anomaly_label"],
                "source_system": "synthetic_swift_generator",
            }
        )

    return raw_messages


def _serialize_mt540(instruction: dict[str, Any]) -> str:
    lines = [
        "{1:F01SYNTHBICAXXX0000000000}{2:I540CUSTBICXXXXN}{4:",
        f":20C::SEME//{instruction['transaction_reference']}",
        f":35B:ISIN {instruction['isin']}",
        f":36B::SETT//UNIT/{instruction['quantity']}",
        f":98A::TRAD//{_format_date(instruction['trade_date'])}",
        f":98A::SETT//{_format_date(instruction['settlement_date'])}",
        f":95P::DEAG//{instruction['counterparty_bic']}",
        f":97A::SAFE//{instruction['safekeeping_account']}",
    ]
    if instruction["settlement_amount"] is not None and instruction["currency"] is not None:
        lines.append(
            f":19A::SETT//{instruction['currency']}{float(instruction['settlement_amount']):.2f}"
        )
    lines.append("-}")
    return "\n".join(lines)


def _serialize_mt548(status: dict[str, Any]) -> str:
    lines = [
        "{1:F01SYNTHBICAXXX0000000000}{2:I548CUSTBICXXXXN}{4:",
        f":20C::RELA//{status['transaction_reference']}",
        f":35B:ISIN {status['isin']}",
        f":25D::IPRC//{status['status']}",
        f":98C::STAT//{_format_datetime(status['reported_at'])}",
    ]
    if status["reason_code"] is not None:
        lines.append(f":24B::REAS//{status['reason_code']}")
    lines.append("-}")
    return "\n".join(lines)


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    lines = [json.dumps(_json_ready(record), sort_keys=True) for record in records]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _json_ready(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    return value


def _date_at_time(value: date, *, hour: int) -> datetime:
    return datetime.combine(value, time(hour=hour), tzinfo=UTC)


def _format_date(value: date) -> str:
    return value.strftime("%Y%m%d")


def _format_datetime(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%d%H%M%S")


def _enum_value(value: Any) -> str:
    return value.value if isinstance(value, StrEnum) else str(value)


def _count_anomalies(instructions: list[dict[str, Any]]) -> dict[str, int]:
    counts = {family.value: 0 for family in AnomalyFamily}
    for instruction in instructions:
        label = instruction.get("anomaly_label")
        if label is not None:
            counts[str(label)] = counts.get(str(label), 0) + 1
    return counts
