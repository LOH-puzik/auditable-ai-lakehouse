"""Executable entry point for one full local pipeline run."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from audit_lakehouse.orchestration.runner import run_pipeline

app = typer.Typer(help="Run the auditable AI pipeline end to end.")
console = Console()


@app.callback(invoke_without_command=True)
def main(
    n: int = typer.Option(25, "--n", help="Number of synthetic instructions to generate."),
    seed: int = typer.Option(42, "--seed", help="Random seed for deterministic generation."),
    anomaly_rate: float = typer.Option(0.08, "--anomaly-rate", help="Synthetic anomaly rate."),
    contamination: float = typer.Option(
        0.08, "--contamination", help="Isolation Forest contamination."
    ),
    n_estimators: int = typer.Option(200, "--n-estimators", help="Isolation Forest tree count."),
    run_id: str | None = typer.Option(None, "--run-id", help="Optional explicit run identifier."),
    data_root: Path = typer.Option(Path("data/runs"), "--data-root", help="Root for run outputs."),
    config: Path = typer.Option(
        Path("config/local-demo.yaml"),
        "--config",
        help="YAML config path.",
    ),
    onchain: bool = typer.Option(False, "--onchain", help="Submit the Merkle root to Aptos."),
) -> None:
    """Execute data generation, medallion processing, modeling, scoring, and anchoring."""
    result = run_pipeline(
        n=n,
        seed=seed,
        anomaly_rate=anomaly_rate,
        contamination=contamination,
        n_estimators=n_estimators,
        run_id=run_id,
        data_root=data_root,
        config_path=config,
        onchain=onchain,
    )

    table = Table(title="audit-lakehouse run")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("run_id", result.run_id)
    table.add_row("run_dir", str(result.run_dir))
    table.add_row("records_generated", str(result.records_generated))
    table.add_row("records_scored", str(result.records_scored))
    table.add_row("alerts_generated", str(result.alerts_generated))
    table.add_row("batch_id", result.batch_id)
    table.add_row("merkle_root", result.merkle_root)
    table.add_row("onchain_anchor", str(result.onchain_anchor).lower())
    table.add_row("tx_hash", result.tx_hash or "<not anchored>")
    table.add_row("manifest", str(result.manifest_path))
    console.print(table)


if __name__ == "__main__":
    app()
