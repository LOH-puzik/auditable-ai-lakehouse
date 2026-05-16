"""Tests for the lightweight orchestration executables."""

from __future__ import annotations

import json
from pathlib import Path

from audit_lakehouse.orchestration.replay_menu import _report_passed, discover_replay_events
from audit_lakehouse.orchestration.run import _env_flag
from audit_lakehouse.orchestration.runner import run_pipeline
from audit_lakehouse.replay.report import ReplayReport


def test_run_pipeline_writes_manifest_and_replay_menu_discovers_events(tmp_path) -> None:
    config_path = _write_test_config(tmp_path)

    result = run_pipeline(
        n=10,
        seed=101,
        anomaly_rate=0.2,
        contamination=0.2,
        n_estimators=10,
        run_id="RUN-TEST",
        data_root=tmp_path / "runs",
        config_path=config_path,
        onchain=False,
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    events = discover_replay_events(
        data_root=tmp_path / "runs",
        limit=20,
        include_notebook_latest=False,
    )

    assert result.run_id == "RUN-TEST"
    assert result.records_generated == 10
    assert result.records_scored == 10
    assert result.batch_id == "BATCH-RUN-TEST"
    assert result.tx_hash == ""
    assert manifest["anchor_batch_manifest_path"] == str(result.anchor_manifest_path)
    assert len(events) == 10
    assert events[0].run_id == "RUN-TEST"
    assert events[0].alert_id.startswith("ALERT-SCORE-RUN-TEST")
    assert events[0].anchor_batch_manifest_path == result.anchor_manifest_path


def test_replay_menu_can_allow_unanchored_local_reports() -> None:
    report = ReplayReport(
        alert_id="ALERT-1",
        batch_id="BATCH-1",
        input_hash_match=True,
        deterministic_score_match=True,
        merkle_proof_valid=True,
        onchain_root_match=False,
        logged_input_hash="a" * 64,
        recomputed_input_hash="a" * 64,
        logged_score=0.1,
        recomputed_score=0.1,
        merkle_root="b" * 64,
        onchain_root="",
        tx_hash="",
    )

    assert not _report_passed(report, allow_unanchored=False)
    assert _report_passed(report, allow_unanchored=True)


def test_run_cli_env_flag_parser(monkeypatch) -> None:
    monkeypatch.delenv("AUDIT_LAKEHOUSE_ANCHOR_ONCHAIN", raising=False)
    assert not _env_flag("AUDIT_LAKEHOUSE_ANCHOR_ONCHAIN", default=False)

    monkeypatch.setenv("AUDIT_LAKEHOUSE_ANCHOR_ONCHAIN", "true")
    assert _env_flag("AUDIT_LAKEHOUSE_ANCHOR_ONCHAIN", default=False)

    monkeypatch.setenv("AUDIT_LAKEHOUSE_ANCHOR_ONCHAIN", "0")
    assert not _env_flag("AUDIT_LAKEHOUSE_ANCHOR_ONCHAIN", default=True)


def test_run_cli_env_flag_parser_reads_dotenv(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("AUDIT_LAKEHOUSE_ANCHOR_ONCHAIN", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "AUDIT_LAKEHOUSE_ANCHOR_ONCHAIN=true\n",
        encoding="utf-8",
    )

    assert _env_flag("AUDIT_LAKEHOUSE_ANCHOR_ONCHAIN", default=False)


def _write_test_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
environment: test
mlflow:
  registered_model_name: audit_lakehouse_isolation_forest
  promotion_thresholds:
    precision: 0.0
    recall: 0.0
    precision_at_k: 0.0
governance:
  approver: test_approver
  deployer: test_deployer
""".strip(),
        encoding="utf-8",
    )
    return config_path
