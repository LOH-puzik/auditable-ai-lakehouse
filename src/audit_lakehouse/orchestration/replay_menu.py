"""Interactive replay menu for previously orchestrated runs."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from audit_lakehouse.anchoring import aptos_explorer_tx_url
from audit_lakehouse.config import load_settings
from audit_lakehouse.replay.cli import replay_alert
from audit_lakehouse.replay.report import ReplayReport
from audit_lakehouse.runtime_env import env_value

app = typer.Typer(help="Choose an existing inference event and replay it.")
console = Console(width=160)


@dataclass(frozen=True)
class ReplayMenuEvent:
    index: int
    run_id: str
    alert_id: str
    decision: str
    score: float
    occurred_at: str
    batch_id: str
    gold_records_path: Path
    promotion_manifest_path: Path
    inference_events_path: Path
    anchor_batch_manifest_path: Path


@app.callback(invoke_without_command=True)
def main(
    data_root: Path = typer.Option(
        Path("data/runs"), "--data-root", help="Root containing run manifests."
    ),
    config: Path = typer.Option(
        Path(env_value("AUDIT_LAKEHOUSE_CONFIG", "config/default.yaml") or "config/default.yaml"),
        "--config",
        help="YAML config path.",
    ),
    limit: int = typer.Option(25, "--limit", help="Maximum number of events to list."),
    index: int | None = typer.Option(
        None, "--index", help="Replay this listed index without prompting."
    ),
    output: Path | None = typer.Option(
        None, "--output", help="Write selected replay JSON to a file."
    ),
    allow_unanchored: bool = typer.Option(
        False,
        "--allow-unanchored",
        help="Exit successfully when local checks pass but the batch is not on-chain anchored.",
    ),
) -> None:
    """List inference events, choose one by index, and run replay."""
    events = discover_replay_events(data_root=data_root, limit=limit)
    if not events:
        raise typer.BadParameter(f"No replayable events found under {data_root}")

    _print_events(events)
    selected_index = index if index is not None else typer.prompt("Choose event index", type=int)
    selected = _event_by_index(events, selected_index)

    with _replay_environment(selected):
        report = replay_alert(selected.alert_id, config_path=config)

    payload = report.to_json()
    if output is not None:
        output.write_text(payload + "\n", encoding="utf-8")
    console.print(payload)
    if report.tx_hash:
        settings = load_settings(config)
        console.print(
            "Aptos Explorer: "
            + aptos_explorer_tx_url(
                report.tx_hash,
                environment=settings.environment,
                node_url=settings.anchoring.node_url,
            )
        )
    if not _report_passed(report, allow_unanchored=allow_unanchored):
        raise typer.Exit(code=1)


def discover_replay_events(
    *,
    data_root: str | Path = "data/runs",
    limit: int = 25,
    include_notebook_latest: bool = True,
) -> list[ReplayMenuEvent]:
    """Discover replayable inference events from orchestrated run manifests."""
    events: list[ReplayMenuEvent] = []
    for manifest in _run_manifests(
        Path(data_root), include_notebook_latest=include_notebook_latest
    ):
        inference_events_path = Path(str(manifest["inference_events_path"]))
        if not inference_events_path.exists():
            continue
        for event in _read_jsonl(inference_events_path):
            if event.get("event_type") != "inference":
                continue
            payload = event.get("payload", {})
            if not isinstance(payload, dict):
                continue
            events.append(
                ReplayMenuEvent(
                    index=len(events),
                    run_id=str(manifest["run_id"]),
                    alert_id=str(payload["alert_id"]),
                    decision=str(payload["decision"]),
                    score=float(payload["score"]),
                    occurred_at=str(event.get("occurred_at", "")),
                    batch_id=str(manifest["batch_id"]),
                    gold_records_path=Path(str(manifest["gold_records_path"])),
                    promotion_manifest_path=Path(str(manifest["promotion_manifest_path"])),
                    inference_events_path=inference_events_path,
                    anchor_batch_manifest_path=Path(str(manifest["anchor_batch_manifest_path"])),
                )
            )
            if len(events) >= limit:
                return events
    return events


def _run_manifests(data_root: Path, *, include_notebook_latest: bool) -> list[dict]:
    manifests = [_read_json(path) for path in data_root.glob("*/run_manifest.json")]
    manifests = sorted(
        manifests,
        key=lambda manifest: str(manifest.get("started_at", "")),
        reverse=True,
    )
    if include_notebook_latest:
        notebook_manifest = _notebook_artifact_manifest()
        if notebook_manifest is not None:
            manifests.append(notebook_manifest)
    return manifests


def _notebook_artifact_manifest() -> dict | None:
    paths = {
        "gold_records_path": Path("data/gold/features/records.jsonl"),
        "promotion_manifest_path": Path(
            "data/model_registry/production/isolation_forest/manifest.json"
        ),
        "inference_events_path": Path("data/governance_events/inference_events.jsonl"),
        "anchor_batch_manifest_path": Path("data/anchor_batches/latest/manifest.json"),
    }
    if not all(path.exists() for path in paths.values()):
        return None
    anchor_manifest = _read_json(paths["anchor_batch_manifest_path"])
    return {
        "run_id": "notebook-latest",
        "batch_id": anchor_manifest.get("batch_id", ""),
        **{key: str(value) for key, value in paths.items()},
    }


def _print_events(events: list[ReplayMenuEvent]) -> None:
    table = Table(
        title="Replayable inference events",
        caption="Use the Index value with --index to replay one event.",
    )
    table.add_column("Index", justify="right", no_wrap=True)
    table.add_column("Run ID", overflow="fold")
    table.add_column("Inference event ID", overflow="fold")
    table.add_column("Model decision", no_wrap=True)
    table.add_column("Model score", justify="right", no_wrap=True)
    table.add_column("Merkle batch ID", overflow="fold")
    for event in events:
        table.add_row(
            str(event.index),
            event.run_id,
            event.alert_id,
            event.decision,
            f"{event.score:.6f}",
            event.batch_id,
        )
    console.print(table)


def _event_by_index(events: list[ReplayMenuEvent], index: int) -> ReplayMenuEvent:
    for event in events:
        if event.index == index:
            return event
    raise typer.BadParameter(f"Index {index} is not in the listed events")


def _report_passed(report: ReplayReport, *, allow_unanchored: bool) -> bool:
    if report.passed:
        return True
    return (
        allow_unanchored
        and report.input_hash_match
        and report.deterministic_score_match
        and report.merkle_proof_valid
        and not report.onchain_root_match
        and not report.onchain_root
    )


@contextmanager
def _replay_environment(event: ReplayMenuEvent) -> Iterator[None]:
    values = {
        "AUDIT_LAKEHOUSE_GOLD_RECORDS": str(event.gold_records_path),
        "AUDIT_LAKEHOUSE_PROMOTION_MANIFEST": str(event.promotion_manifest_path),
        "AUDIT_LAKEHOUSE_INFERENCE_EVENTS": str(event.inference_events_path),
        "AUDIT_LAKEHOUSE_ANCHOR_BATCH_MANIFEST": str(event.anchor_batch_manifest_path),
    }
    previous = {key: os.environ.get(key) for key in values}
    try:
        os.environ.update(values)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


if __name__ == "__main__":
    app()
