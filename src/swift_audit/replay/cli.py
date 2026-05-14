"""Replay CLI.

Per the thesis commitment, accepts either an alert identifier (replays a single
scoring event) or a batch identifier (replays every event in a Merkle batch).
Exactly one must be provided.
"""

from __future__ import annotations

import typer
from rich.console import Console

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
    raise NotImplementedError("Implement in step 6 of the build plan")


if __name__ == "__main__":
    app()
