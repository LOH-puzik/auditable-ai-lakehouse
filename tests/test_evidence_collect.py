"""Tests for evidence pack collection."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from audit_lakehouse.evidence.collect import collect_evidence


def test_collect_evidence_copies_run_artifacts_and_writes_index(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "RUN-EVIDENCE"
    _write_fake_run(run_dir)

    result = collect_evidence(
        run_id="RUN-EVIDENCE",
        data_root=tmp_path / "runs",
        output_root=tmp_path / "evidence",
        generate_reports=False,
        zip_output=True,
    )

    assert result.run_id == "RUN-EVIDENCE"
    assert (result.output_dir / "run_manifest.json").exists()
    assert (result.output_dir / "manifests/bronze_manifest.json").exists()
    assert (result.output_dir / "gold/feature_hash_sample.jsonl").exists()
    assert (result.output_dir / "governance/inference_events_sample.jsonl").exists()
    assert "run_manifest.json" in result.index_path.read_text(encoding="utf-8")
    assert result.zip_path is not None
    with zipfile.ZipFile(result.zip_path) as archive:
        assert "RUN-EVIDENCE/run_manifest.json" in archive.namelist()


def _write_fake_run(run_dir: Path) -> None:
    paths = [
        run_dir / "raw/synthetic_swift/manifest.json",
        run_dir / "bronze/swift_messages/manifest.json",
        run_dir / "silver/swift_messages/manifest.json",
        run_dir / "gold/features/manifest.json",
        run_dir / "models/isolation_forest/manifest.json",
        run_dir / "models/isolation_forest/metrics.json",
        run_dir / "model_registry/production/isolation_forest/manifest.json",
        run_dir / "scoring/inference/manifest.json",
        run_dir / "anchor_batches/latest/manifest.json",
    ]
    for path in paths:
        _write_json(path, {"path": str(path)})

    _write_jsonl(
        run_dir / "gold/features/records.jsonl",
        [
            {
                "gold_record_id": "GOLD-1",
                "transaction_reference": "TRN-1",
                "feature_row_hash": "a" * 64,
            }
        ],
    )
    _write_jsonl(run_dir / "silver_quarantine/swift_messages/records.jsonl", [])
    _write_jsonl(run_dir / "governance_events/quarantine_events.jsonl", [])
    _write_jsonl(run_dir / "governance_events/promotion_events.jsonl", [])
    _write_jsonl(
        run_dir / "governance_events/inference_events.jsonl",
        [{"event_type": "inference", "payload": {"alert_id": "ALERT-1"}}],
    )
    _write_jsonl(run_dir / "anchor_batches/latest/events.jsonl", [])
    _write_jsonl(run_dir / "anchor_batches/latest/proofs.jsonl", [])

    _write_json(
        run_dir / "run_manifest.json",
        {
            "run_id": "RUN-EVIDENCE",
            "batch_id": "BATCH-RUN-EVIDENCE",
            "merkle_root": "b" * 64,
            "tx_hash": "",
            "records_requested": 1,
            "seed": 42,
            "anomaly_rate": 0.1,
            "contamination": 0.1,
            "n_estimators": 10,
            "onchain_anchor": False,
            "config_path": "config/local-demo.yaml",
            "gold_records_path": str(run_dir / "gold/features/records.jsonl"),
            "promotion_manifest_path": str(
                run_dir / "model_registry/production/isolation_forest/manifest.json"
            ),
            "inference_events_path": str(run_dir / "governance_events/inference_events.jsonl"),
            "anchor_batch_manifest_path": str(run_dir / "anchor_batches/latest/manifest.json"),
        },
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )
