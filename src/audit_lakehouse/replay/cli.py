"""Replay CLI.

Per the thesis commitment, accepts either an alert identifier (replays a single
scoring event) or a batch identifier (replays every inference event in a Merkle
batch). Exactly one must be provided.
"""

from __future__ import annotations

import math
from pathlib import Path

import typer
from rich.console import Console

from audit_lakehouse.anchoring import MerkleProof, verify_proof
from audit_lakehouse.replay.inference import rescore
from audit_lakehouse.replay.loader import (
    LoadedSnapshot,
    alert_ids_for_batch,
    load_for_alert,
    read_onchain_root,
)
from audit_lakehouse.replay.report import ReplayBatchReport, ReplayReport

app = typer.Typer(help="Auditor replay tool: reconstruct, re-score, and verify.")
console = Console()


@app.callback(invoke_without_command=True)
def replay(
    alert_id: str | None = typer.Option(None, "--alert-id", help="Replay a single alert."),
    batch_id: str | None = typer.Option(None, "--batch-id", help="Replay every event in a batch."),
    config: str = typer.Option("config/default.yaml", help="Path to YAML config."),
    output: str | None = typer.Option(None, "--output", help="Write the JSON report to a file."),
) -> None:
    """Reconstruct, re-score, and verify one or more governance events."""
    if (alert_id is None) == (batch_id is None):
        raise typer.BadParameter("Provide exactly one of --alert-id or --batch-id.")

    report: ReplayReport | ReplayBatchReport
    if alert_id is not None:
        report = replay_alert(alert_id, config_path=config)
    else:
        assert batch_id is not None
        report = replay_batch(batch_id, config_path=config)

    payload = report.to_json()
    if output is not None:
        Path(output).write_text(payload + "\n", encoding="utf-8")
    console.print(payload)

    if not report.passed:
        raise typer.Exit(code=1)


def replay_alert(
    alert_id: str,
    *,
    config_path: str | Path = "config/default.yaml",
) -> ReplayReport:
    """Build a replay report for one alert."""
    snapshot = load_for_alert(alert_id, config_path=config_path)
    return build_report(snapshot, config_path=config_path)


def replay_batch(
    batch_id: str,
    *,
    config_path: str | Path = "config/default.yaml",
) -> ReplayBatchReport:
    """Build replay reports for every inference event in a Merkle batch."""
    reports = [
        replay_alert(alert_id, config_path=config_path)
        for alert_id in alert_ids_for_batch(batch_id, config_path=config_path)
    ]
    return ReplayBatchReport(batch_id=batch_id, reports=reports)


def build_report(
    snapshot: LoadedSnapshot,
    *,
    config_path: str | Path = "config/default.yaml",
) -> ReplayReport:
    """Compute the four named replay checks for a loaded snapshot."""
    payload = snapshot.inference_event["payload"]
    rescored = rescore(snapshot.model, snapshot.feature_row)
    proof = _proof_from_row(snapshot.proof_row)
    merkle_root = str(snapshot.anchor_manifest["merkle_root"])
    tx_hash = str(snapshot.anchor_manifest.get("tx_hash", ""))
    onchain_root = read_onchain_root(snapshot.anchor_manifest, config_path=config_path)

    return ReplayReport(
        alert_id=snapshot.alert_id,
        batch_id=str(snapshot.anchor_manifest["batch_id"]),
        input_hash_match=snapshot.feature_row_hash == str(payload["input_hash"]),
        deterministic_score_match=_scores_match(rescored.score, float(payload["score"]))
        and rescored.decision == str(payload["decision"]),
        merkle_proof_valid=verify_proof(proof, merkle_root),
        onchain_root_match=bool(onchain_root) and onchain_root == merkle_root,
        logged_input_hash=str(payload["input_hash"]),
        recomputed_input_hash=snapshot.feature_row_hash,
        logged_score=float(payload["score"]),
        recomputed_score=rescored.score,
        merkle_root=merkle_root,
        onchain_root=onchain_root,
        tx_hash=tx_hash,
    )


def _proof_from_row(row: dict) -> MerkleProof:
    return MerkleProof(
        leaf_index=int(row["leaf_index"]),
        leaf_hash=str(row["event_hash"]),
        siblings=[
            (str(sibling["sibling_hash"]), bool(sibling["sibling_is_right"]))
            for sibling in row["siblings"]
        ],
    )


def _scores_match(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-9)


if __name__ == "__main__":
    app()
