"""Tests for the replay report."""

from __future__ import annotations

import json

from swift_audit.replay.report import ReplayReport


def _make_report(**overrides: object) -> ReplayReport:
    defaults: dict[str, object] = dict(
        alert_id="ALERT-1",
        batch_id="BATCH-1",
        input_hash_match=True,
        deterministic_score_match=True,
        merkle_proof_valid=True,
        onchain_root_match=True,
        logged_input_hash="a" * 64,
        recomputed_input_hash="a" * 64,
        logged_score=0.42,
        recomputed_score=0.42,
        merkle_root="b" * 64,
        onchain_root="b" * 64,
        tx_hash="0x" + "c" * 64,
    )
    defaults.update(overrides)
    return ReplayReport(**defaults)  # type: ignore[arg-type]


def test_all_checks_pass_means_passed() -> None:
    assert _make_report().passed is True


def test_any_check_failing_means_not_passed() -> None:
    assert _make_report(input_hash_match=False).passed is False
    assert _make_report(deterministic_score_match=False).passed is False
    assert _make_report(merkle_proof_valid=False).passed is False
    assert _make_report(onchain_root_match=False).passed is False


def test_to_json_round_trips() -> None:
    payload = json.loads(_make_report().to_json())
    assert payload["passed"] is True
    assert payload["alert_id"] == "ALERT-1"
    assert payload["logged_input_hash"] == "a" * 64
