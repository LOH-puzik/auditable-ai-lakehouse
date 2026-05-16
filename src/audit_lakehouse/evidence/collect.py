"""Collect a thesis evidence pack from one orchestrated run."""

from __future__ import annotations

import json
import os
import shutil
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from audit_lakehouse.anchoring.explorer import aptos_explorer_tx_url
from audit_lakehouse.anchoring.verify import verify_batch
from audit_lakehouse.config import load_settings
from audit_lakehouse.replay.cli import replay_alert, replay_batch

app = typer.Typer(help="Collect evidence artifacts for a completed pipeline run.")
console = Console()


@dataclass(frozen=True)
class EvidencePackResult:
    """Output locations for one collected evidence pack."""

    run_id: str
    output_dir: Path
    index_path: Path
    zip_path: Path | None
    files_copied: int


@app.callback(invoke_without_command=True)
def main(
    run_id: str | None = typer.Option(None, "--run-id", help="Run ID to collect."),
    run_dir: Path | None = typer.Option(None, "--run-dir", help="Explicit run directory."),
    data_root: Path = typer.Option(Path("data/runs"), "--data-root", help="Root of run outputs."),
    output_root: Path = typer.Option(Path("evidence"), "--output-root", help="Evidence output root."),
    config: Path | None = typer.Option(None, "--config", help="YAML config path for verification."),
    run_output: Path | None = typer.Option(
        None,
        "--run-output",
        help="Optional captured console output from run.exe.",
    ),
    replay_output: Path | None = typer.Option(
        None,
        "--replay-output",
        help="Optional captured console output from replay-menu.exe.",
    ),
    pytest_output: Path | None = typer.Option(
        None,
        "--pytest-output",
        help="Optional captured pytest output.",
    ),
    zip_output: bool = typer.Option(True, "--zip/--no-zip", help="Create a zip archive."),
    generate_reports: bool = typer.Option(
        True,
        "--generate-reports/--no-generate-reports",
        help="Generate verify-anchor and replay JSON reports from local artifacts.",
    ),
) -> None:
    """Copy run artifacts and generated verification outputs into one evidence folder."""
    result = collect_evidence(
        run_id=run_id,
        run_dir=run_dir,
        data_root=data_root,
        output_root=output_root,
        config_path=config,
        run_output=run_output,
        replay_output=replay_output,
        pytest_output=pytest_output,
        zip_output=zip_output,
        generate_reports=generate_reports,
    )

    table = Table(title="evidence pack")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("run_id", result.run_id)
    table.add_row("output_dir", str(result.output_dir))
    table.add_row("index", str(result.index_path))
    table.add_row("files_copied", str(result.files_copied))
    table.add_row("zip", str(result.zip_path) if result.zip_path else "<not created>")
    console.print(table)


def collect_evidence(
    *,
    run_id: str | None = None,
    run_dir: str | Path | None = None,
    data_root: str | Path = "data/runs",
    output_root: str | Path = "evidence",
    config_path: str | Path | None = None,
    run_output: str | Path | None = None,
    replay_output: str | Path | None = None,
    pytest_output: str | Path | None = None,
    zip_output: bool = True,
    generate_reports: bool = True,
) -> EvidencePackResult:
    """Collect raw artifacts and generated reports for a completed run."""
    source_run_dir = _resolve_run_dir(run_id=run_id, run_dir=run_dir, data_root=data_root)
    manifest_path = source_run_dir / "run_manifest.json"
    manifest = _read_json(manifest_path)
    resolved_run_id = str(manifest["run_id"])

    target = Path(output_root) / resolved_run_id
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)

    copied: dict[str, str] = {}
    copied["run_manifest"] = _copy_file(manifest_path, target / "run_manifest.json", root=target)
    copied.update(_copy_standard_artifacts(source_run_dir, target))
    copied.update(
        _copy_optional_outputs(
            target,
            run_output=run_output,
            replay_output=replay_output,
            pytest_output=pytest_output,
        )
    )
    copied.update(_write_generated_summaries(source_run_dir, target, manifest))

    generated: dict[str, str] = {}
    if generate_reports:
        generated = _generate_reports(
            target,
            manifest,
            config_path=Path(config_path) if config_path is not None else None,
        )

    index_path = target / "EVIDENCE_INDEX.md"
    _write_evidence_index(
        index_path,
        manifest=manifest,
        copied={**copied, **generated},
    )

    zip_path = _zip_directory(target) if zip_output else None
    return EvidencePackResult(
        run_id=resolved_run_id,
        output_dir=target,
        index_path=index_path,
        zip_path=zip_path,
        files_copied=len(copied) + len(generated),
    )


def _copy_standard_artifacts(run_dir: Path, target: Path) -> dict[str, str]:
    artifacts = {
        "raw_manifest": ("raw/synthetic_swift/manifest.json", "manifests/raw_manifest.json"),
        "bronze_manifest": (
            "bronze/swift_messages/manifest.json",
            "manifests/bronze_manifest.json",
        ),
        "silver_manifest": (
            "silver/swift_messages/manifest.json",
            "manifests/silver_manifest.json",
        ),
        "gold_manifest": ("gold/features/manifest.json", "manifests/gold_manifest.json"),
        "gold_records": ("gold/features/records.jsonl", "gold/records.jsonl"),
        "quarantine_records": (
            "silver_quarantine/swift_messages/records.jsonl",
            "governance/quarantine_records.jsonl",
        ),
        "quarantine_events": (
            "governance_events/quarantine_events.jsonl",
            "governance/quarantine_events.jsonl",
        ),
        "training_manifest": (
            "models/isolation_forest/manifest.json",
            "modeling/training_manifest.json",
        ),
        "training_metrics": ("models/isolation_forest/metrics.json", "modeling/metrics.json"),
        "promotion_manifest": (
            "model_registry/production/isolation_forest/manifest.json",
            "modeling/promotion_manifest.json",
        ),
        "promotion_events": (
            "governance_events/promotion_events.jsonl",
            "governance/promotion_events.jsonl",
        ),
        "scoring_manifest": ("scoring/inference/manifest.json", "scoring/manifest.json"),
        "scored_records": ("scoring/inference/records.jsonl", "scoring/records.jsonl"),
        "inference_events": (
            "governance_events/inference_events.jsonl",
            "governance/inference_events.jsonl",
        ),
        "anchor_events": (
            "governance_events/anchor_events.jsonl",
            "governance/anchor_events.jsonl",
        ),
        "anchor_manifest": (
            "anchor_batches/latest/manifest.json",
            "anchoring/manifest.json",
        ),
        "anchor_batch_events": (
            "anchor_batches/latest/events.jsonl",
            "anchoring/events.jsonl",
        ),
        "anchor_batch_proofs": (
            "anchor_batches/latest/proofs.jsonl",
            "anchoring/proofs.jsonl",
        ),
    }

    copied: dict[str, str] = {}
    for label, (source, destination) in artifacts.items():
        source_path = run_dir / source
        if source_path.exists():
            copied[label] = _copy_file(source_path, target / destination, root=target)
    return copied


def _copy_optional_outputs(
    target: Path,
    *,
    run_output: str | Path | None,
    replay_output: str | Path | None,
    pytest_output: str | Path | None,
) -> dict[str, str]:
    outputs = {
        "run_console_output": (run_output, "console/run_output.txt"),
        "replay_console_output": (replay_output, "console/replay_output.txt"),
        "pytest_output": (pytest_output, "console/pytest_output.txt"),
    }
    copied: dict[str, str] = {}
    for label, (source, destination) in outputs.items():
        if source is not None and Path(source).exists():
            copied[label] = _copy_file(Path(source), target / destination, root=target)
    return copied


def _write_generated_summaries(run_dir: Path, target: Path, manifest: dict[str, Any]) -> dict[str, str]:
    copied: dict[str, str] = {}
    command_path = target / "console/reconstructed_run_command.txt"
    command_path.parent.mkdir(parents=True, exist_ok=True)
    command_path.write_text(_reconstructed_run_command(manifest) + "\n", encoding="utf-8")
    copied["reconstructed_run_command"] = _relative(command_path, target)

    gold_records = run_dir / "gold/features/records.jsonl"
    if gold_records.exists():
        sample_path = target / "gold/feature_hash_sample.jsonl"
        _write_feature_hash_sample(gold_records, sample_path)
        copied["gold_feature_hash_sample"] = _relative(sample_path, target)

    inference_events = run_dir / "governance_events/inference_events.jsonl"
    if inference_events.exists():
        sample_path = target / "governance/inference_events_sample.jsonl"
        _write_jsonl_sample(inference_events, sample_path, limit=5)
        copied["inference_events_sample"] = _relative(sample_path, target)

    tx_hash = str(manifest.get("tx_hash", ""))
    if tx_hash:
        config_path = Path(str(manifest.get("config_path", "config/aptos-testnet.yaml")))
        settings = load_settings(config_path)
        explorer_path = target / "anchoring/aptos_explorer_url.txt"
        explorer_path.parent.mkdir(parents=True, exist_ok=True)
        explorer_path.write_text(
            aptos_explorer_tx_url(
                tx_hash,
                environment=settings.environment,
                node_url=settings.anchoring.node_url,
            )
            + "\n",
            encoding="utf-8",
        )
        copied["aptos_explorer_url"] = _relative(explorer_path, target)

    screenshots_readme = target / "screenshots/README.md"
    screenshots_readme.parent.mkdir(parents=True, exist_ok=True)
    screenshots_readme.write_text(
        "# Manual Screenshots\n\n"
        "Add the Aptos Explorer transaction screenshot and MLflow run screenshot here.\n",
        encoding="utf-8",
    )
    copied["screenshots_placeholder"] = _relative(screenshots_readme, target)
    return copied


def _generate_reports(
    target: Path,
    manifest: dict[str, Any],
    *,
    config_path: Path | None,
) -> dict[str, str]:
    generated: dict[str, str] = {}
    config = config_path or Path(str(manifest.get("config_path", "config/aptos-testnet.yaml")))
    batch_id = str(manifest["batch_id"])
    anchor_manifest_path = Path(str(manifest["anchor_batch_manifest_path"]))

    report_dir = target / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    with _evidence_environment(manifest):
        generated["verify_anchor_output"] = _write_report_or_error(
            report_dir / "verify_anchor_output.json",
            lambda: verify_batch(batch_id, config_path=config).to_dict(),
        )
        alert_id = _first_alert_id(Path(str(manifest["inference_events_path"])))
        if alert_id:
            generated["replay_alert_output"] = _write_report_or_error(
                report_dir / "replay_alert_output.json",
                lambda: replay_alert(alert_id, config_path=config).to_dict(),
            )
        generated["replay_batch_output"] = _write_report_or_error(
            report_dir / "replay_batch_output.json",
            lambda: replay_batch(batch_id, config_path=config).to_dict(),
        )

    if anchor_manifest_path.exists():
        generated["anchor_manifest_source"] = _relative(anchor_manifest_path, Path.cwd())
    return {key: _relative(target / value, target) if not value.endswith(".json") else value for key, value in generated.items()}


def _write_report_or_error(path: Path, producer) -> str:
    try:
        payload = producer()
    except Exception as exc:  # pragma: no cover - defensive evidence capture.
        payload = {"passed": False, "error": f"{type(exc).__name__}: {exc}"}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return _relative(path, path.parents[1])


@contextmanager
def _evidence_environment(manifest: dict[str, Any]) -> Iterator[None]:
    values = {
        "AUDIT_LAKEHOUSE_GOLD_RECORDS": str(manifest["gold_records_path"]),
        "AUDIT_LAKEHOUSE_PROMOTION_MANIFEST": str(manifest["promotion_manifest_path"]),
        "AUDIT_LAKEHOUSE_INFERENCE_EVENTS": str(manifest["inference_events_path"]),
        "AUDIT_LAKEHOUSE_ANCHOR_BATCH_MANIFEST": str(manifest["anchor_batch_manifest_path"]),
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


def _write_evidence_index(
    path: Path,
    *,
    manifest: dict[str, Any],
    copied: dict[str, str],
) -> None:
    copied = _with_combined_evidence_locations(copied)
    rows = [
        ("Exact command used to run the pipeline", "reconstructed_run_command"),
        ("Full console output from run / audit-lakehouse-run", "run_console_output"),
        ("run_manifest.json", "run_manifest"),
        ("Bronze, Silver and Gold manifest files", "layer_manifests"),
        ("Quarantine event output, even if zero quarantines", "quarantine_events"),
        ("Gold records manifest and feature hash evidence", "gold_feature_hash_sample"),
        ("Training manifest and metrics.json", "training_artifacts"),
        ("Promotion manifest", "promotion_manifest"),
        ("Scoring manifest and sample inference events", "scoring_artifacts"),
        ("Anchor batch manifest.json", "anchor_manifest"),
        ("verify-anchor output", "verify_anchor_output"),
        ("replay output for one alert and one batch", "replay_outputs"),
        ("Aptos Explorer transaction screenshot or URL", "aptos_explorer_url"),
        ("MLflow run screenshot or exported run metadata", "training_manifest"),
        ("pytest -q or CI output", "pytest_output"),
        ("Git commit SHA used for the final run", "git_commit"),
    ]

    git_commit = _git_commit()
    lines = [
        f"# Evidence Pack: {manifest['run_id']}",
        "",
        f"- Run ID: `{manifest['run_id']}`",
        f"- Batch ID: `{manifest['batch_id']}`",
        f"- Merkle root: `{manifest['merkle_root']}`",
        f"- Transaction hash: `{manifest.get('tx_hash') or '<not anchored>'}`",
        f"- Git commit: `{git_commit}`",
        "",
        "| Evidence needed | Status | Location |",
        "| --- | --- | --- |",
    ]
    copied = {**copied, "git_commit": git_commit}
    for label, key in rows:
        value = copied.get(key, "")
        status = "present" if value else "missing/manual"
        location = f"`{value}`" if value else ""
        lines.append(f"| {label} | {status} | {location} |")

    lines.extend(
        [
            "",
            "## Manual Items",
            "",
            "- Add an Aptos Explorer screenshot to `screenshots/` after the live testnet run.",
            "- Add an MLflow screenshot to `screenshots/` if it is used in Chapter 5.",
            "- Capture command output with `Tee-Object` if exact console logs are needed.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _with_combined_evidence_locations(copied: dict[str, str]) -> dict[str, str]:
    combined = dict(copied)
    _combine_locations(
        combined,
        "layer_manifests",
        ["bronze_manifest", "silver_manifest", "gold_manifest"],
    )
    _combine_locations(
        combined,
        "training_artifacts",
        ["training_manifest", "training_metrics"],
    )
    _combine_locations(
        combined,
        "scoring_artifacts",
        ["scoring_manifest", "inference_events_sample"],
    )
    _combine_locations(
        combined,
        "replay_outputs",
        ["replay_alert_output", "replay_batch_output"],
    )
    return combined


def _combine_locations(copied: dict[str, str], target_key: str, source_keys: list[str]) -> None:
    values = [copied[key] for key in source_keys if copied.get(key)]
    if values:
        copied[target_key] = "; ".join(values)


def _resolve_run_dir(
    *,
    run_id: str | None,
    run_dir: str | Path | None,
    data_root: str | Path,
) -> Path:
    if run_dir is not None:
        candidate = Path(run_dir)
    elif run_id is not None:
        candidate = Path(data_root) / run_id
    else:
        manifests = sorted(Path(data_root).glob("*/run_manifest.json"), key=lambda path: path.stat().st_mtime)
        if not manifests:
            raise FileNotFoundError(f"No run_manifest.json files found under {data_root}")
        candidate = manifests[-1].parent

    if not (candidate / "run_manifest.json").exists():
        raise FileNotFoundError(f"Run manifest does not exist: {candidate / 'run_manifest.json'}")
    return candidate


def _copy_file(source: Path, destination: Path, *, root: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return _relative(destination, root)


def _write_feature_hash_sample(source: Path, destination: Path, *, limit: int = 20) -> None:
    rows = []
    for row in _read_jsonl(source)[:limit]:
        rows.append(
            {
                "gold_record_id": row.get("gold_record_id"),
                "transaction_reference": row.get("transaction_reference"),
                "feature_row_hash": row.get("feature_row_hash"),
            }
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def _write_jsonl_sample(source: Path, destination: Path, *, limit: int) -> None:
    rows = _read_jsonl(source)[:limit]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def _first_alert_id(path: Path) -> str:
    for event in _read_jsonl(path):
        payload = event.get("payload", {})
        if isinstance(payload, dict) and payload.get("alert_id"):
            return str(payload["alert_id"])
    return ""


def _reconstructed_run_command(manifest: dict[str, Any]) -> str:
    command = [
        r".\.venv\Scripts\run.exe",
        "--n",
        str(manifest["records_requested"]),
        "--seed",
        str(manifest["seed"]),
        "--anomaly-rate",
        str(manifest["anomaly_rate"]),
        "--contamination",
        str(manifest["contamination"]),
        "--n-estimators",
        str(manifest["n_estimators"]),
        "--run-id",
        str(manifest["run_id"]),
        "--config",
        str(manifest["config_path"]),
    ]
    if not manifest.get("onchain_anchor", False):
        command.append("--local-only")
    return " ".join(command)


def _zip_directory(directory: Path) -> Path:
    zip_path = directory.with_suffix(".zip")
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(directory.parent))
    return zip_path


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _git_commit() -> str:
    head = Path(".git/HEAD")
    if not head.exists():
        return "unknown"
    value = head.read_text(encoding="utf-8").strip()
    if not value.startswith("ref: "):
        return value
    ref_path = Path(".git") / value.removeprefix("ref: ")
    return ref_path.read_text(encoding="utf-8").strip() if ref_path.exists() else "unknown"


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    app()
