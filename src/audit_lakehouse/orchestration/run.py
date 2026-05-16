"""Executable entry point for one full local pipeline run."""

from __future__ import annotations

import os
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from audit_lakehouse.anchoring import aptos_explorer_tx_url
from audit_lakehouse.config import load_settings
from audit_lakehouse.orchestration.runner import run_pipeline
from audit_lakehouse.runtime_env import env_flag, env_value

app = typer.Typer(help="Run the auditable AI pipeline end to end.")
console = Console()
PRIVATE_KEY_ENV = "AUDIT_LAKEHOUSE_ANCHORING_PRIVATE_KEY"


def _env_flag(name: str, *, default: bool) -> bool:
    return env_flag(name, default=default)


def _ensure_private_key_for_onchain(onchain: bool) -> None:
    if not onchain or _has_private_key():
        return

    private_key = typer.prompt("Aptos private key", hide_input=True)
    if not _looks_like_private_key(private_key):
        raise typer.BadParameter("A valid Aptos private key is required for on-chain anchoring.")
    os.environ[PRIVATE_KEY_ENV] = private_key.strip()


def _has_private_key() -> bool:
    return _looks_like_private_key(env_value(PRIVATE_KEY_ENV, "") or "")


def _looks_like_private_key(value: str) -> bool:
    key = value.strip()
    return bool(key) and "..." not in key


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
        Path(
            env_value("AUDIT_LAKEHOUSE_CONFIG", "config/local-demo.yaml")
            or "config/local-demo.yaml"
        ),
        "--config",
        help="YAML config path.",
    ),
    onchain: bool = typer.Option(
        _env_flag("AUDIT_LAKEHOUSE_ANCHOR_ONCHAIN", default=False),
        "--onchain/--local-only",
        help="Submit the Merkle root to Aptos.",
    ),
) -> None:
    """Execute data generation, medallion processing, modeling, scoring, and anchoring."""
    _ensure_private_key_for_onchain(onchain)
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
    if result.tx_hash:
        settings = load_settings(config)
        table.add_row(
            "aptos_explorer",
            aptos_explorer_tx_url(
                result.tx_hash,
                environment=settings.environment,
                node_url=settings.anchoring.node_url,
            ),
        )
    table.add_row("manifest", str(result.manifest_path))
    console.print(table)


if __name__ == "__main__":
    app()
