"""Standalone anchor verification.

This entry point implements the Chapter 1 commitment to a *verification script*
that is separate from the full replay flow: an auditor can verify the integrity
of a Merkle batch (root matches on-chain, all leaves are in the off-chain log)
without re-running model inference.
"""

from __future__ import annotations

import typer

cli = typer.Typer(help="Verify the integrity of an anchored Merkle batch.")


@cli.command()
def verify(
    batch_id: str = typer.Option(..., help="Batch identifier to verify."),
    config: str = typer.Option("config/default.yaml", help="Path to YAML config."),
) -> None:
    """Verify that the off-chain batch matches the on-chain anchored root."""
    raise NotImplementedError("Implement in step 5 of the build plan")


if __name__ == "__main__":
    cli()
