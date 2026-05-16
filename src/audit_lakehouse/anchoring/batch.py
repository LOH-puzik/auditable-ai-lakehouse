"""Build local Merkle anchor batches from governance event JSONL files."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from audit_lakehouse.anchoring.ledger import AnchorReceipt, LedgerClient
from audit_lakehouse.anchoring.merkle import MerkleProof, build_tree
from audit_lakehouse.events import AnchorEvent
from audit_lakehouse.hashing import sha256_hex


@dataclass(frozen=True)
class AnchorBatchResult:
    """Artifacts and counts produced by local Merkle batching."""

    event_paths: list[Path]
    output_dir: Path
    events_path: Path
    proofs_path: Path
    manifest_path: Path
    batch_id: str
    merkle_root: str
    leaf_count: int


@dataclass(frozen=True)
class OnChainAnchorResult:
    """Artifacts and receipt produced by committing a batch root to a ledger."""

    manifest_path: Path
    governance_events_path: Path
    batch_id: str
    merkle_root: str
    tx_hash: str
    block_number: int
    event_written: bool


def build_anchor_batch(
    event_paths: list[str | Path],
    output_dir: str | Path,
    *,
    batch_id: str | None = None,
    built_at: datetime | None = None,
) -> AnchorBatchResult:
    """Read governance events, build a Merkle tree, and write event proofs."""
    source_paths = [Path(path) for path in event_paths]
    if not source_paths:
        raise ValueError("event_paths must not be empty")

    build_time = built_at or datetime.now(UTC)
    if build_time.tzinfo is None:
        raise ValueError("built_at must be timezone-aware")
    build_time = build_time.astimezone(UTC)
    anchor_batch_id = batch_id or f"BATCH-{build_time.strftime('%Y%m%d%H%M%S')}"

    events = _read_events(source_paths)
    if not events:
        raise ValueError("No governance events found to anchor")

    leaf_hashes = [str(event["event_hash"]) for event in events]
    tree = build_tree(leaf_hashes)
    event_rows = [
        {
            **event,
            "batch_id": anchor_batch_id,
            "leaf_index": index,
            "merkle_root": tree.root,
        }
        for index, event in enumerate(events)
    ]
    proof_rows = [
        _proof_to_record(
            proof,
            batch_id=anchor_batch_id,
            event=events[proof.leaf_index],
            merkle_root=tree.root,
        )
        for proof in tree.proofs
    ]

    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    events_path = target_dir / "events.jsonl"
    proofs_path = target_dir / "proofs.jsonl"
    manifest_path = target_dir / "manifest.json"

    _write_jsonl(events_path, event_rows)
    _write_jsonl(proofs_path, proof_rows)

    manifest = {
        "stage": "build_anchor_batch",
        "batch_id": anchor_batch_id,
        "built_at": build_time,
        "merkle_root": tree.root,
        "leaf_count": len(events),
        "source_event_files": [str(path) for path in source_paths],
        "events_path": str(events_path),
        "proofs_path": str(proofs_path),
        "anchored": False,
        "tx_hash": "",
        "block_number": 0,
        "batch_manifest_hash": sha256_hex(
            {
                "batch_id": anchor_batch_id,
                "merkle_root": tree.root,
                "leaf_hashes": leaf_hashes,
            }
        ),
    }
    manifest_path.write_text(
        json.dumps(_json_ready(manifest), indent=2, sort_keys=True),
        encoding="utf-8",
    )

    return AnchorBatchResult(
        event_paths=source_paths,
        output_dir=target_dir,
        events_path=events_path,
        proofs_path=proofs_path,
        manifest_path=manifest_path,
        batch_id=anchor_batch_id,
        merkle_root=tree.root,
        leaf_count=len(events),
    )


def finalize_anchor_batch(
    manifest_path: str | Path,
    ledger_client: LedgerClient,
    governance_events_path: str | Path,
    *,
    actor: str = "anchor_job",
    anchored_at: datetime | None = None,
) -> OnChainAnchorResult:
    """Commit a local batch root to a ledger and emit an AnchorEvent."""
    manifest_source = Path(manifest_path)
    events_path = Path(governance_events_path)
    if not manifest_source.exists():
        raise FileNotFoundError(f"Anchor batch manifest does not exist: {manifest_source}")

    anchor_time = anchored_at or datetime.now(UTC)
    if anchor_time.tzinfo is None:
        raise ValueError("anchored_at must be timezone-aware")
    anchor_time = anchor_time.astimezone(UTC)

    manifest = json.loads(manifest_source.read_text(encoding="utf-8"))
    merkle_root = str(manifest["merkle_root"])
    receipt = ledger_client.commit_root(merkle_root)
    onchain_root = receipt.merkle_root
    if onchain_root != merkle_root:
        raise ValueError(
            f"On-chain root mismatch: committed {merkle_root}, read back {onchain_root}"
        )

    manifest.update(
        {
            "anchored": True,
            "anchored_at": anchor_time,
            "tx_hash": receipt.tx_hash,
            "block_number": receipt.block_number,
            "onchain_root": onchain_root,
            "anchor_event_path": str(events_path),
        }
    )
    manifest["batch_manifest_hash"] = sha256_hex(
        {
            "batch_id": manifest["batch_id"],
            "merkle_root": manifest["merkle_root"],
            "leaf_count": manifest["leaf_count"],
            "tx_hash": manifest["tx_hash"],
            "block_number": manifest["block_number"],
        }
    )
    manifest_source.write_text(
        json.dumps(_json_ready(manifest), indent=2, sort_keys=True),
        encoding="utf-8",
    )

    event = _build_anchor_event(manifest, receipt=receipt, actor=actor)
    _append_jsonl(events_path, [event])

    return OnChainAnchorResult(
        manifest_path=manifest_source,
        governance_events_path=events_path,
        batch_id=str(manifest["batch_id"]),
        merkle_root=merkle_root,
        tx_hash=receipt.tx_hash,
        block_number=receipt.block_number,
        event_written=True,
    )


def _read_events(paths: list[Path]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for path in paths:
        if not path.exists():
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on line {line_number} of {path}") from exc
            if not isinstance(event, dict):
                raise ValueError(f"Expected JSON object on line {line_number} of {path}")
            event_hash = _event_hash(event)
            events.append(
                {
                    **event,
                    "event_hash": event_hash,
                    "source_file": str(path),
                    "source_line_number": line_number,
                }
            )
    return sorted(
        events,
        key=lambda event: (
            str(event.get("occurred_at", "")),
            str(event.get("event_id", "")),
            str(event.get("source_file", "")),
            int(event.get("source_line_number", 0)),
        ),
    )


def _event_hash(event: dict[str, Any]) -> str:
    existing_hash = event.get("event_hash")
    if isinstance(existing_hash, str) and len(existing_hash) == 64:
        return existing_hash
    return sha256_hex({key: value for key, value in event.items() if key != "event_hash"})


def _proof_to_record(
    proof: MerkleProof,
    *,
    batch_id: str,
    event: dict[str, Any],
    merkle_root: str,
) -> dict[str, Any]:
    return {
        "batch_id": batch_id,
        "event_id": event.get("event_id", ""),
        "event_type": event.get("event_type", ""),
        "event_hash": proof.leaf_hash,
        "leaf_index": proof.leaf_index,
        "merkle_root": merkle_root,
        "siblings": [
            {"sibling_hash": sibling_hash, "sibling_is_right": sibling_is_right}
            for sibling_hash, sibling_is_right in proof.siblings
        ],
    }


def _build_anchor_event(
    manifest: dict[str, Any],
    *,
    receipt: AnchorReceipt,
    actor: str,
) -> dict[str, Any]:
    payload = {
        "batch_id": str(manifest["batch_id"]),
        "merkle_root": str(manifest["merkle_root"]),
        "leaf_count": int(manifest["leaf_count"]),
        "tx_hash": receipt.tx_hash,
        "block_number": receipt.block_number,
        "events_path": str(manifest["events_path"]),
        "proofs_path": str(manifest["proofs_path"]),
        "batch_manifest_hash": str(manifest["batch_manifest_hash"]),
    }
    event = AnchorEvent(actor=actor, payload=payload)
    data = event.model_dump(mode="json")
    data["event_hash"] = event.to_hash()
    return data


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    lines = [json.dumps(_json_ready(record), sort_keys=True) for record in records]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _append_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = [json.dumps(_json_ready(record), sort_keys=True) for record in records]
    payload = "\n".join(lines) + ("\n" if lines else "")
    separator = "" if not existing or existing.endswith("\n") else "\n"
    path.write_text(existing + separator + payload, encoding="utf-8")


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
