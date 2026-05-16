"""End-to-end local pipeline runner.

This module intentionally stays small: it orchestrates the package functions
already used by the notebooks and writes one run directory containing all local
artifacts plus a manifest for replay-menu discovery.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from audit_lakehouse.anchoring import AptosLedgerClient, build_anchor_batch, finalize_anchor_batch
from audit_lakehouse.config import load_settings
from audit_lakehouse.generator import generate_synthetic_swift_dataset
from audit_lakehouse.lakehouse import (
    build_gold_features,
    ingest_bronze_raw_messages,
    parse_validate_silver,
)
from audit_lakehouse.modeling import promote_model, score_gold_features, train_isolation_forest


@dataclass(frozen=True)
class PipelineRunResult:
    """Summary of one orchestrated local run."""

    run_id: str
    run_dir: Path
    manifest_path: Path
    gold_records_path: Path
    promotion_manifest_path: Path
    inference_events_path: Path
    anchor_manifest_path: Path
    batch_id: str
    merkle_root: str
    tx_hash: str
    onchain_anchor: bool
    records_generated: int
    records_scored: int
    alerts_generated: int


def run_pipeline(
    *,
    n: int = 25,
    seed: int = 42,
    anomaly_rate: float = 0.08,
    contamination: float = 0.08,
    n_estimators: int = 200,
    run_id: str | None = None,
    data_root: str | Path = "data/runs",
    config_path: str | Path = "config/local-demo.yaml",
    onchain: bool = False,
) -> PipelineRunResult:
    """Run the full local ingest-model-audit pipeline once."""
    if n <= 0:
        raise ValueError("n must be greater than zero")
    if not 0 <= anomaly_rate <= 1:
        raise ValueError("anomaly_rate must be between 0 and 1")
    if not 0 < contamination < 0.5:
        raise ValueError("contamination must be between 0 and 0.5")

    settings = load_settings(config_path)
    started_at = datetime.now(UTC)
    pipeline_run_id = run_id or f"RUN-{started_at.strftime('%Y%m%d%H%M%S')}"
    run_dir = Path(data_root) / pipeline_run_id

    paths = _run_paths(run_dir)
    paths["governance_events_dir"].mkdir(parents=True, exist_ok=True)

    dataset = generate_synthetic_swift_dataset(n, seed=seed, anomaly_rate=anomaly_rate)
    raw_paths = dataset.write_jsonl(paths["raw_dir"])

    bronze = ingest_bronze_raw_messages(
        raw_paths["raw_messages"],
        paths["bronze_dir"],
        batch_id=f"BRONZE-{pipeline_run_id}",
        ingested_at=started_at,
    )
    silver = parse_validate_silver(
        bronze.records_path,
        paths["silver_dir"],
        paths["quarantine_dir"],
        paths["quarantine_events_path"],
        validation_batch_id=f"SILVER-{pipeline_run_id}",
        validated_at=started_at,
    )
    gold = build_gold_features(
        silver.instructions_path,
        silver.statuses_path,
        paths["gold_dir"],
        gold_snapshot_id=f"GOLD-{pipeline_run_id}",
        built_at=started_at,
    )
    training = train_isolation_forest(
        gold.records_path,
        paths["model_dir"],
        tracking_uri=paths["mlruns_dir"].resolve().as_uri(),
        experiment_name=f"audit-lakehouse-{pipeline_run_id}",
        seed=seed,
        contamination=contamination,
        n_estimators=n_estimators,
        training_run_id=f"TRAIN-{pipeline_run_id}",
        trained_at=started_at,
    )
    promotion = promote_model(
        training.manifest_path,
        paths["registry_dir"],
        paths["promotion_events_path"],
        model_name=settings.mlflow.registered_model_name,
        thresholds=settings.mlflow.promotion_thresholds,
        approver=settings.governance.approver,
        promotion_id=f"PROMOTE-{pipeline_run_id}",
        promoted_at=started_at,
    )
    scoring = score_gold_features(
        gold.records_path,
        promotion.manifest_path,
        paths["scoring_dir"],
        paths["inference_events_path"],
        scoring_batch_id=f"SCORE-{pipeline_run_id}",
        scored_at=started_at,
    )
    batch = build_anchor_batch(
        [
            paths["quarantine_events_path"],
            paths["promotion_events_path"],
            paths["inference_events_path"],
        ],
        paths["anchor_batch_dir"],
        batch_id=f"BATCH-{pipeline_run_id}",
        built_at=started_at,
    )

    tx_hash = ""
    if onchain:
        private_key = settings.anchoring_private_key.get_secret_value()
        if not private_key:
            raise ValueError("AUDIT_LAKEHOUSE_ANCHORING_PRIVATE_KEY is required for --onchain")
        ledger = AptosLedgerClient(
            node_url=settings.anchoring.node_url,
            private_key=private_key,
            account_address=settings.anchoring.account_address,
            module_address=settings.anchoring.module_address,
            module_name=settings.anchoring.module_name,
            function_name=settings.anchoring.function_name,
            event_name=settings.anchoring.event_name,
            max_gas_amount=settings.anchoring.max_gas_amount,
            gas_unit_price=settings.anchoring.gas_unit_price,
        )
        anchored = finalize_anchor_batch(
            batch.manifest_path,
            ledger,
            paths["anchor_events_path"],
            anchored_at=started_at,
        )
        tx_hash = anchored.tx_hash

    result = PipelineRunResult(
        run_id=pipeline_run_id,
        run_dir=run_dir,
        manifest_path=paths["run_manifest_path"],
        gold_records_path=gold.records_path,
        promotion_manifest_path=promotion.manifest_path,
        inference_events_path=scoring.governance_events_path,
        anchor_manifest_path=batch.manifest_path,
        batch_id=batch.batch_id,
        merkle_root=batch.merkle_root,
        tx_hash=tx_hash,
        onchain_anchor=onchain,
        records_generated=n,
        records_scored=scoring.records_scored,
        alerts_generated=scoring.alerts_generated,
    )
    _write_run_manifest(
        result,
        started_at=started_at,
        config_path=Path(config_path),
        seed=seed,
        anomaly_rate=anomaly_rate,
        contamination=contamination,
        n_estimators=n_estimators,
    )
    return result


def _run_paths(run_dir: Path) -> dict[str, Path]:
    governance_events_dir = run_dir / "governance_events"
    return {
        "run_manifest_path": run_dir / "run_manifest.json",
        "raw_dir": run_dir / "raw" / "synthetic_swift",
        "bronze_dir": run_dir / "bronze" / "swift_messages",
        "silver_dir": run_dir / "silver" / "swift_messages",
        "quarantine_dir": run_dir / "silver_quarantine" / "swift_messages",
        "governance_events_dir": governance_events_dir,
        "quarantine_events_path": governance_events_dir / "quarantine_events.jsonl",
        "promotion_events_path": governance_events_dir / "promotion_events.jsonl",
        "inference_events_path": governance_events_dir / "inference_events.jsonl",
        "anchor_events_path": governance_events_dir / "anchor_events.jsonl",
        "gold_dir": run_dir / "gold" / "features",
        "model_dir": run_dir / "models" / "isolation_forest",
        "mlruns_dir": run_dir / "mlruns",
        "registry_dir": run_dir / "model_registry" / "production" / "isolation_forest",
        "scoring_dir": run_dir / "scoring" / "inference",
        "anchor_batch_dir": run_dir / "anchor_batches" / "latest",
    }


def _write_run_manifest(
    result: PipelineRunResult,
    *,
    started_at: datetime,
    config_path: Path,
    seed: int,
    anomaly_rate: float,
    contamination: float,
    n_estimators: int,
) -> None:
    manifest: dict[str, Any] = {
        "stage": "orchestrated_pipeline_run",
        "run_id": result.run_id,
        "started_at": started_at.isoformat(),
        "config_path": str(config_path),
        "seed": seed,
        "records_requested": result.records_generated,
        "anomaly_rate": anomaly_rate,
        "contamination": contamination,
        "n_estimators": n_estimators,
        "run_dir": str(result.run_dir),
        "gold_records_path": str(result.gold_records_path),
        "promotion_manifest_path": str(result.promotion_manifest_path),
        "inference_events_path": str(result.inference_events_path),
        "anchor_batch_manifest_path": str(result.anchor_manifest_path),
        "batch_id": result.batch_id,
        "merkle_root": result.merkle_root,
        "tx_hash": result.tx_hash,
        "onchain_anchor": result.onchain_anchor,
        "records_scored": result.records_scored,
        "alerts_generated": result.alerts_generated,
    }
    result.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    result.manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
