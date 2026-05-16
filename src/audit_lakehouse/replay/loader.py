"""Snapshot and model loading for replay.

The local prototype stores replay evidence as JSONL artifacts:
  - inference governance events
  - Gold feature records
  - the promoted model manifest and model artifact
  - Merkle batch events, proofs, and manifest

These helpers keep that filesystem lookup logic out of the CLI and return a
single read-only context for the auditor report builder.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib

from audit_lakehouse.anchoring import AptosLedgerClient
from audit_lakehouse.config import load_settings
from audit_lakehouse.hashing import sha256_hex
from audit_lakehouse.lakehouse.gold import MODEL_FEATURE_COLUMNS


@dataclass(frozen=True)
class ReplayPaths:
    """Filesystem inputs needed to replay scoring decisions."""

    gold_records_path: Path
    promotion_manifest_path: Path
    inference_events_path: Path
    anchor_batches_dir: Path
    anchor_batch_manifest_path: Path | None = None


@dataclass(frozen=True)
class LoadedSnapshot:
    """A reconstructed scoring context: the input row plus the model used."""

    alert_id: str
    feature_row: dict[str, Any]
    feature_row_hash: str
    model_name: str
    model_version: str
    model: Any
    inference_event: dict[str, Any]
    anchor_event: dict[str, Any]
    proof_row: dict[str, Any]
    anchor_manifest: dict[str, Any]
    promotion_manifest: dict[str, Any]


def load_for_alert(
    alert_id: str,
    *,
    config_path: str | Path = "config/default.yaml",
    paths: ReplayPaths | None = None,
) -> LoadedSnapshot:
    """Resolve an alert_id into its full scoring context."""
    replay_paths = paths or resolve_replay_paths(config_path)
    inference_event = _find_inference_event(alert_id, replay_paths.inference_events_path)
    payload = _payload(inference_event)
    feature_row = _find_feature_row(payload, replay_paths.gold_records_path)
    promotion_manifest = _read_json(replay_paths.promotion_manifest_path)
    model_path = Path(str(promotion_manifest.get("promoted_model_path", "")))
    if not model_path.exists():
        raise FileNotFoundError(f"Promoted model artifact does not exist: {model_path}")

    anchor_manifest_path = _find_anchor_manifest_for_alert(
        alert_id,
        replay_paths,
    )
    anchor_manifest = _read_json(anchor_manifest_path)
    anchor_event = _find_anchor_event(alert_id, Path(str(anchor_manifest["events_path"])))
    proof_row = _find_proof_row(anchor_event, Path(str(anchor_manifest["proofs_path"])))

    return LoadedSnapshot(
        alert_id=alert_id,
        feature_row=feature_row,
        feature_row_hash=recompute_feature_row_hash(feature_row),
        model_name=str(payload["model_name"]),
        model_version=str(payload["model_version"]),
        model=joblib.load(model_path),
        inference_event=inference_event,
        anchor_event=anchor_event,
        proof_row=proof_row,
        anchor_manifest=anchor_manifest,
        promotion_manifest=promotion_manifest,
    )


def alert_ids_for_batch(
    batch_id: str,
    *,
    config_path: str | Path = "config/default.yaml",
    paths: ReplayPaths | None = None,
) -> list[str]:
    """Return the inference alert IDs contained in a Merkle batch."""
    replay_paths = paths or resolve_replay_paths(config_path)
    manifest_path = _find_anchor_manifest_for_batch(batch_id, replay_paths)
    manifest = _read_json(manifest_path)
    events = _read_jsonl(Path(str(manifest["events_path"])))
    alert_ids = [
        str(_payload(event)["alert_id"])
        for event in events
        if event.get("event_type") == "inference" and "alert_id" in _payload(event)
    ]
    if not alert_ids:
        raise ValueError(f"No inference events found in batch {batch_id!r}")
    return alert_ids


def resolve_replay_paths(config_path: str | Path = "config/default.yaml") -> ReplayPaths:
    """Resolve replay paths from environment variables, falling back to local defaults."""
    root = _repo_root(Path(config_path))
    return ReplayPaths(
        gold_records_path=Path(
            os.getenv(
                "AUDIT_LAKEHOUSE_GOLD_RECORDS", str(root / "data/gold/features/records.jsonl")
            )
        ),
        promotion_manifest_path=Path(
            os.getenv(
                "AUDIT_LAKEHOUSE_PROMOTION_MANIFEST",
                str(root / "data/model_registry/production/isolation_forest/manifest.json"),
            )
        ),
        inference_events_path=Path(
            os.getenv(
                "AUDIT_LAKEHOUSE_INFERENCE_EVENTS",
                str(root / "data/governance_events/inference_events.jsonl"),
            )
        ),
        anchor_batches_dir=Path(
            os.getenv("AUDIT_LAKEHOUSE_ANCHOR_BATCHES_DIR", str(root / "data/anchor_batches"))
        ),
        anchor_batch_manifest_path=(
            Path(os.environ["AUDIT_LAKEHOUSE_ANCHOR_BATCH_MANIFEST"])
            if "AUDIT_LAKEHOUSE_ANCHOR_BATCH_MANIFEST" in os.environ
            else None
        ),
    )


def recompute_feature_row_hash(feature_row: dict[str, Any]) -> str:
    """Recompute the Gold feature row hash using the Gold builder contract."""
    feature_columns = feature_row.get("feature_columns")
    columns = (
        [str(column) for column in feature_columns]
        if isinstance(feature_columns, list) and feature_columns
        else MODEL_FEATURE_COLUMNS
    )
    missing = [column for column in columns if column not in feature_row]
    if missing:
        raise ValueError(f"Gold feature row is missing feature columns: {missing}")

    return sha256_hex(
        {
            "transaction_reference": str(feature_row["transaction_reference"]),
            "features": {column: feature_row[column] for column in columns},
        }
    )


def read_onchain_root(
    anchor_manifest: dict[str, Any],
    *,
    config_path: str | Path = "config/default.yaml",
) -> str:
    """Read the anchored root from Aptos when configured; otherwise use manifest evidence."""
    tx_hash = str(anchor_manifest.get("tx_hash", ""))
    manifest_root = str(anchor_manifest.get("onchain_root", ""))
    if not tx_hash:
        return manifest_root

    settings = load_settings(config_path)
    module_address = settings.anchoring.module_address or settings.anchoring.account_address
    if not module_address:
        return manifest_root

    ledger = AptosLedgerClient(
        node_url=settings.anchoring.node_url,
        module_address=module_address,
        module_name=settings.anchoring.module_name,
        function_name=settings.anchoring.function_name,
        event_name=settings.anchoring.event_name,
        max_gas_amount=settings.anchoring.max_gas_amount,
        gas_unit_price=settings.anchoring.gas_unit_price,
    )
    return ledger.read_root(tx_hash)


def _find_inference_event(alert_id: str, path: Path) -> dict[str, Any]:
    for event in _read_jsonl(path):
        payload = _payload(event)
        if event.get("event_type") == "inference" and payload.get("alert_id") == alert_id:
            return event
    raise ValueError(f"Inference event not found for alert_id {alert_id!r} in {path}")


def _find_feature_row(payload: dict[str, Any], path: Path) -> dict[str, Any]:
    gold_record_id = str(payload.get("gold_record_id", ""))
    input_hash = str(payload["input_hash"])
    for row in _read_jsonl(path):
        if gold_record_id and row.get("gold_record_id") == gold_record_id:
            return row
        if row.get("feature_row_hash") == input_hash:
            return row
    raise ValueError(
        f"Gold feature row not found for gold_record_id={gold_record_id!r} input_hash={input_hash}"
    )


def _find_anchor_manifest_for_alert(alert_id: str, paths: ReplayPaths) -> Path:
    for manifest_path in _candidate_anchor_manifests(paths):
        manifest = _read_json(manifest_path)
        events_path = Path(str(manifest["events_path"]))
        if not events_path.exists():
            continue
        for event in _read_jsonl(events_path):
            if (
                event.get("event_type") == "inference"
                and _payload(event).get("alert_id") == alert_id
            ):
                return manifest_path
    raise ValueError(f"Anchor batch containing alert_id {alert_id!r} was not found")


def _find_anchor_manifest_for_batch(batch_id: str, paths: ReplayPaths) -> Path:
    for manifest_path in _candidate_anchor_manifests(paths):
        manifest = _read_json(manifest_path)
        if manifest.get("batch_id") == batch_id:
            return manifest_path
    raise ValueError(f"Anchor batch manifest not found for batch_id {batch_id!r}")


def _candidate_anchor_manifests(paths: ReplayPaths) -> list[Path]:
    if paths.anchor_batch_manifest_path is not None:
        if not paths.anchor_batch_manifest_path.exists():
            raise FileNotFoundError(
                f"Anchor batch manifest does not exist: {paths.anchor_batch_manifest_path}"
            )
        return [paths.anchor_batch_manifest_path]
    if not paths.anchor_batches_dir.exists():
        raise FileNotFoundError(
            f"Anchor batches directory does not exist: {paths.anchor_batches_dir}"
        )
    return sorted(paths.anchor_batches_dir.rglob("manifest.json"))


def _find_anchor_event(alert_id: str, events_path: Path) -> dict[str, Any]:
    for event in _read_jsonl(events_path):
        if event.get("event_type") == "inference" and _payload(event).get("alert_id") == alert_id:
            return event
    raise ValueError(f"Anchored inference event not found for alert_id {alert_id!r}")


def _find_proof_row(anchor_event: dict[str, Any], proofs_path: Path) -> dict[str, Any]:
    event_hash = str(anchor_event["event_hash"])
    for proof in _read_jsonl(proofs_path):
        if proof.get("event_hash") == event_hash:
            return proof
    raise ValueError(f"Merkle proof not found for event_hash {event_hash}")


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload")
    if not isinstance(payload, dict):
        raise ValueError(f"Governance event payload must be an object: {event!r}")
    return payload


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"JSON file does not exist: {path}")
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"JSONL file does not exist: {path}")
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        line = line.lstrip("\ufeff")
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON on line {line_number} of {path}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"Expected JSON object on line {line_number} of {path}")
        rows.append(value)
    return rows


def _repo_root(config_path: Path) -> Path:
    start = config_path if config_path.is_absolute() else Path.cwd() / config_path
    candidates = [start.parent, *start.parent.parents, Path.cwd(), *Path.cwd().parents]
    for candidate in candidates:
        if (candidate / "pyproject.toml").exists():
            return candidate
    return Path.cwd()
