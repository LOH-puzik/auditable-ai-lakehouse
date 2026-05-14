"""Render the compliance mapping YAML to markdown for the docs and thesis."""

from __future__ import annotations

from pathlib import Path

import typer
import yaml

cli = typer.Typer(help="Render compliance/mapping.yaml to markdown.")

DEFAULT_MAPPING = Path(__file__).parent / "mapping.yaml"


@cli.command()
def render(
    mapping: Path = typer.Option(DEFAULT_MAPPING, help="Path to the mapping YAML."),
    output: Path = typer.Option(Path("docs/compliance-mapping.md"), help="Output markdown path."),
) -> None:
    """Render the mapping YAML to a structured markdown document."""
    data = yaml.safe_load(mapping.read_text())
    lines = [
        "# Compliance mapping",
        "",
        "_Generated from `compliance/mapping.yaml` — do not edit by hand._",
        "",
    ]
    for component in data.get("components", []):
        lines.append(f"## {component['name']}")
        lines.append("")
        lines.append(f"**Component id:** `{component['id']}`")
        lines.append("")
        for obligation in component.get("obligations", []):
            framework = obligation["framework"].upper()
            ref = obligation.get("article") or obligation.get("principle") or ""
            topic = obligation.get("topic", "")
            lines.append(f"### {framework} — {ref}: {topic}")
            lines.append("")
            lines.append(obligation.get("rationale", "").strip())
            lines.append("")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines))
    typer.echo(f"Wrote {output}")


if __name__ == "__main__":
    cli()
