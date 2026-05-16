"""Tests for local Merkle anchor batch construction."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from audit_lakehouse.anchoring import (
    MerkleProof,
    build_anchor_batch,
    finalize_anchor_batch,
    verify_proof,
)
from audit_lakehouse.anchoring.ledger import AnchorReceipt
from audit_lakehouse.events import InferenceEvent, PromotionEvent


def test_build_anchor_batch_writes_events_proofs_and_manifest(tmp_path) -> None:
    first_events = [
        _event_row(
            PromotionEvent(
                actor="approver",
                occurred_at=datetime(2026, 1, 5, tzinfo=UTC),
                payload={
                    "model_name": "model",
                    "model_version": "v1",
                    "from_stage": "Staging",
                    "to_stage": "Production",
                    "metrics": {"precision": 1.0},
                    "mlflow_run_id": "run-1",
                },
            )
        )
    ]
    second_events = [
        _event_row(
            InferenceEvent(
                actor="scoring",
                occurred_at=datetime(2026, 1, 6, tzinfo=UTC),
                payload={
                    "alert_id": "ALERT-1",
                    "input_hash": "a" * 64,
                    "gold_snapshot_version": "GOLD-1",
                    "model_name": "model",
                    "model_version": "v1",
                    "score": 0.2,
                    "decision": "clear",
                },
            )
        ),
        _event_row(
            InferenceEvent(
                actor="scoring",
                occurred_at=datetime(2026, 1, 6, 1, tzinfo=UTC),
                payload={
                    "alert_id": "ALERT-2",
                    "input_hash": "b" * 64,
                    "gold_snapshot_version": "GOLD-1",
                    "model_name": "model",
                    "model_version": "v1",
                    "score": 1.2,
                    "decision": "alert",
                },
            )
        ),
    ]
    first_path = _write_jsonl(tmp_path / "promotion_events.jsonl", first_events)
    second_path = _write_jsonl(tmp_path / "inference_events.jsonl", second_events)

    result = build_anchor_batch(
        [first_path, tmp_path / "missing.jsonl", second_path],
        tmp_path / "anchor_batch",
        batch_id="BATCH-TEST",
        built_at=datetime(2026, 1, 7, tzinfo=UTC),
    )

    events = _read_jsonl(result.events_path)
    proofs = _read_jsonl(result.proofs_path)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

    assert result.batch_id == "BATCH-TEST"
    assert result.leaf_count == 3
    assert len(result.merkle_root) == 64
    assert len(events) == 3
    assert len(proofs) == 3
    assert manifest["anchored"] is False
    assert manifest["tx_hash"] == ""
    assert manifest["leaf_count"] == 3
    assert len(manifest["batch_manifest_hash"]) == 64
    assert [event["leaf_index"] for event in events] == [0, 1, 2]
    assert all(proof["merkle_root"] == result.merkle_root for proof in proofs)

    for proof_row in proofs:
        proof = MerkleProof(
            leaf_index=proof_row["leaf_index"],
            leaf_hash=proof_row["event_hash"],
            siblings=[
                (sibling["sibling_hash"], sibling["sibling_is_right"])
                for sibling in proof_row["siblings"]
            ],
        )
        assert verify_proof(proof, result.merkle_root)


def test_build_anchor_batch_computes_missing_event_hash(tmp_path) -> None:
    event = {
        "event_id": "event-1",
        "event_type": "inference",
        "occurred_at": "2026-01-06T00:00:00+00:00",
        "actor": "scoring",
        "payload": {"alert_id": "ALERT-1"},
    }
    path = _write_jsonl(tmp_path / "events.jsonl", [event])

    result = build_anchor_batch(
        [path],
        tmp_path / "anchor_batch",
        batch_id="BATCH-HASH",
        built_at=datetime(2026, 1, 7, tzinfo=UTC),
    )

    events = _read_jsonl(result.events_path)
    proofs = _read_jsonl(result.proofs_path)

    assert len(events[0]["event_hash"]) == 64
    assert result.merkle_root == events[0]["event_hash"]
    assert proofs[0]["siblings"] == []


def test_finalize_anchor_batch_updates_manifest_and_emits_anchor_event(tmp_path) -> None:
    path = _write_jsonl(tmp_path / "events.jsonl", [_event_row(_minimal_inference_event())])
    batch = build_anchor_batch(
        [path],
        tmp_path / "anchor_batch",
        batch_id="BATCH-ONCHAIN",
        built_at=datetime(2026, 1, 7, tzinfo=UTC),
    )
    ledger = _FakeLedger(root=batch.merkle_root)

    result = finalize_anchor_batch(
        batch.manifest_path,
        ledger,
        tmp_path / "anchor_events.jsonl",
        actor="anchor_actor",
        anchored_at=datetime(2026, 1, 8, tzinfo=UTC),
    )

    manifest = json.loads(batch.manifest_path.read_text(encoding="utf-8"))
    events = _read_jsonl(result.governance_events_path)

    assert result.batch_id == "BATCH-ONCHAIN"
    assert result.tx_hash == "0x" + "c" * 64
    assert result.block_number == 123
    assert result.event_written is True
    assert manifest["anchored"] is True
    assert manifest["onchain_root"] == batch.merkle_root
    assert manifest["tx_hash"] == result.tx_hash
    assert len(events) == 1
    assert events[0]["event_type"] == "anchor"
    assert events[0]["actor"] == "anchor_actor"
    assert events[0]["payload"]["batch_id"] == "BATCH-ONCHAIN"
    assert events[0]["payload"]["merkle_root"] == batch.merkle_root


def test_finalize_anchor_batch_rejects_onchain_root_mismatch(tmp_path) -> None:
    path = _write_jsonl(tmp_path / "events.jsonl", [_event_row(_minimal_inference_event())])
    batch = build_anchor_batch(
        [path],
        tmp_path / "anchor_batch",
        batch_id="BATCH-MISMATCH",
        built_at=datetime(2026, 1, 7, tzinfo=UTC),
    )
    ledger = _FakeLedger(root="d" * 64)

    with pytest.raises(ValueError, match="On-chain root mismatch"):
        finalize_anchor_batch(
            batch.manifest_path,
            ledger,
            tmp_path / "anchor_events.jsonl",
        )


def test_build_anchor_batch_rejects_empty_event_path_list(tmp_path) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        build_anchor_batch([], tmp_path / "anchor_batch")


def test_build_anchor_batch_rejects_when_no_events_found(tmp_path) -> None:
    empty_path = _write_jsonl(tmp_path / "empty.jsonl", [])

    with pytest.raises(ValueError, match="No governance events"):
        build_anchor_batch([empty_path], tmp_path / "anchor_batch")


def test_build_anchor_batch_rejects_naive_build_time(tmp_path) -> None:
    path = _write_jsonl(tmp_path / "events.jsonl", [_event_row(_minimal_inference_event())])

    with pytest.raises(ValueError, match="timezone-aware"):
        build_anchor_batch(
            [path],
            tmp_path / "anchor_batch",
            built_at=datetime(2026, 1, 7),
        )


def _minimal_inference_event() -> InferenceEvent:
    return InferenceEvent(
        actor="scoring",
        payload={
            "alert_id": "ALERT-1",
            "input_hash": "a" * 64,
            "gold_snapshot_version": "GOLD-1",
            "model_name": "model",
            "model_version": "v1",
            "score": 0.2,
            "decision": "clear",
        },
    )


def _event_row(event: InferenceEvent | PromotionEvent) -> dict:
    row = event.model_dump(mode="json")
    row["event_hash"] = event.to_hash()
    return row


def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )
    return path


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class _FakeLedger:
    def __init__(self, *, root: str) -> None:
        self.root = root

    def commit_root(self, merkle_root: str) -> AnchorReceipt:
        return AnchorReceipt(
            tx_hash="0x" + "c" * 64,
            block_number=123,
            merkle_root=merkle_root,
        )

    def read_root(self, tx_hash: str) -> str:
        return self.root
