"""Tests for standalone anchor verification."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from audit_lakehouse.anchoring import build_anchor_batch
from audit_lakehouse.anchoring.verify import verify_batch
from audit_lakehouse.events import InferenceEvent, PromotionEvent


def test_verify_batch_passes_for_complete_local_anchor_evidence(tmp_path, monkeypatch) -> None:
    evidence = _build_anchor_evidence(tmp_path)
    monkeypatch.setenv("AUDIT_LAKEHOUSE_ANCHOR_BATCHES_DIR", str(evidence["anchor_batches_dir"]))

    report = verify_batch("BATCH-VERIFY")

    assert report.passed is True
    assert report.manifest_leaf_count_match is True
    assert report.source_events_match is True
    assert report.all_merkle_proofs_valid is True
    assert report.onchain_root_match is True
    assert report.tx_hash == "0x" + "e" * 64


def test_verify_batch_fails_for_tampered_proof(tmp_path, monkeypatch) -> None:
    evidence = _build_anchor_evidence(tmp_path)
    monkeypatch.setenv("AUDIT_LAKEHOUSE_ANCHOR_BATCHES_DIR", str(evidence["anchor_batches_dir"]))
    proofs_path = Path(evidence["proofs_path"])
    proofs = _read_jsonl(proofs_path)
    proofs[0]["siblings"][0]["sibling_hash"] = "f" * 64
    _write_jsonl(proofs_path, proofs)

    report = verify_batch("BATCH-VERIFY")

    assert report.passed is False
    assert report.all_merkle_proofs_valid is False
    assert report.onchain_root_match is True


def _build_anchor_evidence(tmp_path: Path) -> dict[str, Path]:
    source_path = _write_jsonl(
        tmp_path / "governance_events.jsonl",
        [_event_row(_promotion_event()), _event_row(_inference_event())],
    )
    batch = build_anchor_batch(
        [source_path],
        tmp_path / "anchor_batches" / "latest",
        batch_id="BATCH-VERIFY",
        built_at=datetime(2026, 1, 7, tzinfo=UTC),
    )
    _mark_batch_as_anchored(batch.manifest_path, tx_hash="0x" + "e" * 64)
    return {
        "anchor_batches_dir": tmp_path / "anchor_batches",
        "proofs_path": batch.proofs_path,
    }


def _promotion_event() -> PromotionEvent:
    return PromotionEvent(
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


def _inference_event() -> InferenceEvent:
    return InferenceEvent(
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


def _event_row(event: PromotionEvent | InferenceEvent) -> dict:
    row = event.model_dump(mode="json")
    row["event_hash"] = event.to_hash()
    return row


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


def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )
    return path


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
