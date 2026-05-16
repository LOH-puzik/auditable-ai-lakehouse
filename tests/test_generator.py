"""Tests for synthetic SWIFT message generation."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, date, datetime

import pytest

from swift_audit.generator import (
    AnomalyFamily,
    SettlementStatus,
    generate_mt540,
    generate_mt548_chain,
    generate_synthetic_swift_dataset,
    inject_anomalies,
)


def test_generate_mt540_is_deterministic() -> None:
    assert generate_mt540(5, seed=123) == generate_mt540(5, seed=123)
    assert generate_mt540(5, seed=123) != generate_mt540(5, seed=124)


def test_generate_mt540_has_expected_shape() -> None:
    messages = generate_mt540(20, seed=42)

    assert len(messages) == 20
    assert len({message.transaction_reference for message in messages}) == 20

    for message in messages:
        assert message.transaction_reference.startswith("SEME")
        assert len(message.isin) == 12
        assert message.quantity > 0
        assert message.trade_date <= message.settlement_date
        assert len(message.counterparty_bic) in {8, 11}
        assert message.safekeeping_account.startswith("SAFE")
        assert (message.settlement_amount is None) == (message.currency is None)


def test_generate_mt540_rejects_negative_count() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        generate_mt540(-1)


def test_generate_mt548_chain_is_ordered_and_timezone_aware() -> None:
    chain = generate_mt548_chain("SEME000100000001", seed=7)

    assert [message.status for message in chain] == [
        SettlementStatus.PENDING,
        SettlementStatus.MATCHED,
        SettlementStatus.SETTLED,
    ]
    assert [message.reported_at for message in chain] == sorted(
        message.reported_at for message in chain
    )
    assert all(message.reported_at.tzinfo is UTC for message in chain)
    assert all(message.reason_code is None for message in chain)


def test_generate_mt548_failure_chain_has_reasoned_failure() -> None:
    chain = generate_mt548_chain("SEME000100000001", seed=7, inject_failure=True)

    assert [message.status for message in chain] == [
        SettlementStatus.PENDING,
        SettlementStatus.UNMATCHED,
        SettlementStatus.FAILED,
    ]
    assert chain[0].reason_code is None
    assert chain[1].reason_code is not None
    assert chain[2].reason_code == chain[1].reason_code


def test_generate_mt548_rejects_empty_reference() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        generate_mt548_chain("")


def test_inject_anomalies_is_deterministic_and_does_not_mutate_input() -> None:
    records = [asdict(message) for message in generate_mt540(20, seed=11)]
    original = [dict(record) for record in records]

    first = inject_anomalies(records, rate=0.2, seed=99)
    second = inject_anomalies(records, rate=0.2, seed=99)

    assert first == second
    assert records == original
    assert sum(record["anomaly_label"] is not None for record in first) == 4


def test_inject_anomalies_rejects_invalid_rate() -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        inject_anomalies([], rate=1.1)


def test_duplicate_reference_anomaly_creates_duplicate_reference() -> None:
    records = [asdict(message) for message in generate_mt540(2, seed=12)]

    injected = inject_anomalies(
        records,
        rate=1,
        families=[AnomalyFamily.DUPLICATE_REFERENCE],
        seed=1,
    )

    assert injected[0]["transaction_reference"] == injected[1]["transaction_reference"]
    assert all(
        record["anomaly_label"] == AnomalyFamily.DUPLICATE_REFERENCE.value for record in injected
    )


def test_mismatched_isin_anomaly_adds_conflicting_status_isin() -> None:
    records = [asdict(generate_mt540(1, seed=13)[0])]

    injected = inject_anomalies(
        records,
        rate=1,
        families=[AnomalyFamily.MISMATCHED_ISIN],
        seed=1,
    )

    assert injected[0]["mt548_isin"] != injected[0]["isin"]
    assert injected[0]["anomaly_label"] == AnomalyFamily.MISMATCHED_ISIN.value


def test_late_settlement_anomaly_moves_reported_at_past_settlement() -> None:
    records = [asdict(generate_mt540(1, seed=14)[0])]

    injected = inject_anomalies(
        records,
        rate=1,
        families=[AnomalyFamily.LATE_SETTLEMENT],
        seed=1,
    )

    reported_at = injected[0]["reported_at"]
    assert isinstance(reported_at, datetime)
    assert reported_at.tzinfo is UTC
    assert reported_at.date() > injected[0]["settlement_date"]
    assert injected[0]["status"] == "PENF"


def test_quantity_outlier_anomaly_increases_quantity() -> None:
    records = [asdict(generate_mt540(1, seed=15)[0])]
    original_quantity = records[0]["quantity"]

    injected = inject_anomalies(
        records,
        rate=1,
        families=[AnomalyFamily.QUANTITY_OUTLIER],
        seed=1,
    )

    assert injected[0]["quantity"] > original_quantity * 10


def test_counterparty_drift_anomaly_sets_new_counterparty() -> None:
    records = [asdict(generate_mt540(1, seed=16)[0])]

    injected = inject_anomalies(
        records,
        rate=1,
        families=[AnomalyFamily.COUNTERPARTY_DRIFT],
        seed=1,
    )

    assert injected[0]["counterparty_bic"] == "DRFTGB2LXXX"
    assert injected[0]["counterparty_first_seen_days_ago"] == 0


def test_zero_rate_only_adds_normal_labels() -> None:
    records = [asdict(message) for message in generate_mt540(3, seed=17)]

    injected = inject_anomalies(records, rate=0)

    assert all(record["anomaly_label"] is None for record in injected)
    assert all(isinstance(record["trade_date"], date) for record in injected)


def test_generate_synthetic_swift_dataset_builds_expected_tables() -> None:
    dataset = generate_synthetic_swift_dataset(10, seed=21, anomaly_rate=0.2)

    assert dataset.manifest["instruction_count"] == 10
    assert dataset.manifest["status_count"] >= 10
    assert dataset.manifest["raw_message_count"] == len(dataset.raw_messages)
    assert len(dataset.instructions) == 10
    assert len(dataset.statuses) == dataset.manifest["status_count"]
    assert len(dataset.raw_messages) == len(dataset.instructions) + len(dataset.statuses)
    assert {message["message_type"] for message in dataset.raw_messages} == {"MT540", "MT548"}
    assert sum(record["anomaly_label"] is not None for record in dataset.instructions) == 2


def test_synthetic_swift_dataset_writes_json_outputs(tmp_path) -> None:
    dataset = generate_synthetic_swift_dataset(3, seed=22, anomaly_rate=0)

    paths = dataset.write_jsonl(tmp_path)

    assert set(paths) == {"instructions", "statuses", "raw_messages", "manifest"}
    assert all(path.exists() for path in paths.values())

    instruction_rows = [
        json.loads(line) for line in paths["instructions"].read_text(encoding="utf-8").splitlines()
    ]
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))

    assert len(instruction_rows) == 3
    assert instruction_rows[0]["trade_date"].count("-") == 2
    assert manifest["instruction_count"] == 3
    assert manifest["files"]["raw_messages"] == "raw_messages.jsonl"


def test_late_settlement_dataset_contains_pending_late_status() -> None:
    dataset = generate_synthetic_swift_dataset(
        3,
        seed=23,
        anomaly_rate=1,
        anomaly_families=[AnomalyFamily.LATE_SETTLEMENT],
    )

    late_statuses = [
        status
        for status in dataset.statuses
        if status["anomaly_label"] == AnomalyFamily.LATE_SETTLEMENT.value
    ]
    assert len(late_statuses) == 3
    assert all(status["status"] == SettlementStatus.PENDING.value for status in late_statuses)
