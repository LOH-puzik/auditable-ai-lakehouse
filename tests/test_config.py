"""Tests for configuration loading boundaries."""

from __future__ import annotations

from pathlib import Path

from audit_lakehouse.config import load_settings


def test_load_settings_ignores_yaml_private_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("AUDIT_LAKEHOUSE_ANCHORING_PRIVATE_KEY", raising=False)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
environment: test
anchoring_private_key: 0x1111111111111111111111111111111111111111111111111111111111111111
""".strip(),
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert settings.anchoring_private_key.get_secret_value() == ""
