"""Standalone anchor verification.

This entry point implements the Chapter 1 commitment to a verification script
that is separate from the full replay flow: an auditor can verify the integrity
of a Merkle batch without re-running model inference.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from audit_lakehouse.anchoring import AptosLedgerClient, MerkleProof, verify_proof
from audit_lakehouse.config import load_settings
from audit_lakehouse.hashing import sha256_hex

cli = typer.Typer(help="Verify the integrity of an anchored Merkle batch.")
console = Console()


@dataclass(frozen=True)
class AnchorVerificationReport:
    """Named checks and evidence for a Merkle anchor batch."""

    batch_id: str
    manifest_path: str
    events_path: str
    proofs_path: str
    leaf_count: int
    event_count: int
    proof_count: int
    merkle_root: str
    onchain_root: str
    tx_hash: str
    manifest_leaf_count_match: bool
    event_batch_ids_match: bool
    event_roots_match: bool
    proof_roots_match: bool
    proof_leaf_set_match: bool
    source_events_match: bool
    all_merkle_proofs_valid: bool
    onchain_root_match: bool

    @property
    def passed(self) -> bool:
        return (
            self.manifest_leaf_count_match
            and self.event_batch_ids_match
            and self.event_roots_match
            and self.proof_roots_match
            and self.proof_leaf_set_match
            and self.source_events_match
            and self.all_merkle_proofs_valid
            and self.onchain_root_match
        )

    def to_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, **asdict(self)}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


@cli.callback(invoke_without_command=True)
def verify(
    batch_id: str = typer.Option(..., help="Batch identifier to verify."),
    config: str = typer.Option("config/default.yaml", help="Path to YAML config."),
    output: str | None = typer.Option(None, "--output", help="Write the JSON report to a file."),
) -> None:
    """Verify that the off-chain batch matches its anchored root."""
    report = verify_batch(batch_id, config_path=config)
    payload = report.to_json()
    if output is not None:
        Path(output).write_text(payload + "\n", encoding="utf-8")
    console.print(payload)
    if not report.passed:
        raise typer.Exit(code=1)


def verify_batch(
    batch_id: str,
    *,
    config_path: str | Path = "config/default.yaml",
) -> AnchorVerificationReport:
    """Verify a Merkle batch from local artifacts and, if configured, Aptos."""
    manifest_path = _find_anchor_manifest(batch_id, config_path=config_path)
    manifest = _read_json(manifest_path)
    events_path = Path(str(manifest["events_path"]))
    proofs_path = Path(str(manifest["proofs_path"]))
    events = _read_jsonl(events_path)
    proofs = _read_jsonl(proofs_path)
    merkle_root = str(manifest["merkle_root"])
    leaf_count = int(manifest["leaf_count"])
    onchain_root = _read_onchain_root(manifest, config_path=config_path)

    event_hashes = [str(event.get("event_hash", "")) for event in events]
    proof_hashes = [str(proof.get("event_hash", "")) for proof in proofs]

    return AnchorVerificationReport(
        batch_id=batch_id,
        manifest_path=str(manifest_path),
        events_path=str(events_path),
        proofs_path=str(proofs_path),
        leaf_count=leaf_count,
        event_count=len(events),
        proof_count=len(proofs),
        merkle_root=merkle_root,
        onchain_root=onchain_root,
        tx_hash=str(manifest.get("tx_hash", "")),
        manifest_leaf_count_match=leaf_count == len(events) == len(proofs),
        event_batch_ids_match=all(event.get("batch_id") == batch_id for event in events),
        event_roots_match=all(event.get("merkle_root") == merkle_root for event in events),
        proof_roots_match=all(proof.get("merkle_root") == merkle_root for proof in proofs),
        proof_leaf_set_match=Counter(event_hashes) == Counter(proof_hashes),
        source_events_match=all(_source_event_matches(event) for event in events),
        all_merkle_proofs_valid=all(_verify_proof_row(proof, merkle_root) for proof in proofs),
        onchain_root_match=bool(onchain_root) and onchain_root == merkle_root,
    )


def _find_anchor_manifest(batch_id: str, *, config_path: str | Path) -> Path:
    explicit_manifest = os.getenv("AUDIT_LAKEHOUSE_ANCHOR_BATCH_MANIFEST")
    if explicit_manifest:
        manifest_path = Path(explicit_manifest)
        manifest = _read_json(manifest_path)
        if manifest.get("batch_id") != batch_id:
            raise ValueError(
                f"Manifest {manifest_path} has batch_id {manifest.get('batch_id')!r}, "
                f"expected {batch_id!r}"
            )
        return manifest_path

    root = _repo_root(Path(config_path))
    batches_dir = Path(
        os.getenv("AUDIT_LAKEHOUSE_ANCHOR_BATCHES_DIR", str(root / "data/anchor_batches"))
    )
    if not batches_dir.exists():
        raise FileNotFoundError(f"Anchor batches directory does not exist: {batches_dir}")

    for manifest_path in sorted(batches_dir.rglob("manifest.json")):
        manifest = _read_json(manifest_path)
        if manifest.get("batch_id") == batch_id:
            return manifest_path
    raise ValueError(f"Anchor batch manifest not found for batch_id {batch_id!r}")


def _verify_proof_row(row: dict[str, Any], merkle_root: str) -> bool:
    proof = MerkleProof(
        leaf_index=int(row["leaf_index"]),
        leaf_hash=str(row["event_hash"]),
        siblings=[
            (str(sibling["sibling_hash"]), bool(sibling["sibling_is_right"]))
            for sibling in row.get("siblings", [])
        ],
    )
    return verify_proof(proof, merkle_root)


def _source_event_matches(event: dict[str, Any]) -> bool:
    source_file = event.get("source_file")
    source_line_number = event.get("source_line_number")
    if not source_file or source_line_number is None:
        return False

    source_path = Path(str(source_file))
    if not source_path.exists():
        return False

    source_lines = source_path.read_text(encoding="utf-8").splitlines()
    line_index = int(source_line_number) - 1
    if line_index < 0 or line_index >= len(source_lines):
        return False

    source_event = json.loads(source_lines[line_index])
    if not isinstance(source_event, dict):
        return False
    source_hash = source_event.get("event_hash")
    if not isinstance(source_hash, str) or len(source_hash) != 64:
        source_hash = sha256_hex(
            {key: value for key, value in source_event.items() if key != "event_hash"}
        )
    return source_hash == event.get("event_hash")


def _read_onchain_root(manifest: dict[str, Any], *, config_path: str | Path) -> str:
    tx_hash = str(manifest.get("tx_hash", ""))
    manifest_root = str(manifest.get("onchain_root", ""))
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


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"JSON file does not exist: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"JSONL file does not exist: {path}")
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
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


if __name__ == "__main__":
    cli()
