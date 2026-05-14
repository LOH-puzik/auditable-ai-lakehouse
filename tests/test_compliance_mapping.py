"""Tests for the compliance mapping YAML.

The mapping is the source of truth for Chapter 4 — any change must keep it
schema-valid so the docs render and the thesis tables stay correct.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ALLOWED_FRAMEWORKS = {"eu_ai_act", "bcbs_239", "eba", "gdpr"}
MAPPING_PATH = Path(__file__).parent.parent / "src/swift_audit/compliance/mapping.yaml"


def test_mapping_loads() -> None:
    data = yaml.safe_load(MAPPING_PATH.read_text())
    assert "components" in data
    assert isinstance(data["components"], list)
    assert data["components"]


def test_every_component_has_required_fields() -> None:
    data = yaml.safe_load(MAPPING_PATH.read_text())
    for component in data["components"]:
        assert "id" in component
        assert "name" in component
        assert "obligations" in component
        assert isinstance(component["obligations"], list)
        assert component["obligations"]


def test_every_obligation_has_known_framework() -> None:
    data = yaml.safe_load(MAPPING_PATH.read_text())
    for component in data["components"]:
        for obligation in component["obligations"]:
            assert obligation["framework"] in ALLOWED_FRAMEWORKS
            assert "rationale" in obligation
            assert obligation["rationale"].strip()


def test_eu_ai_act_articles_9_10_12_13_17_are_all_covered() -> None:
    """Chapter 1 commits to mapping Articles 9, 10, 12, 13, and 17."""
    data = yaml.safe_load(MAPPING_PATH.read_text())
    covered = set()
    for component in data["components"]:
        for obligation in component["obligations"]:
            if obligation["framework"] == "eu_ai_act":
                article = obligation.get("article", "")
                for n in ("9", "10", "12", "13", "17"):
                    if f"Article {n}" in article:
                        covered.add(n)
    assert covered == {
        "9",
        "10",
        "12",
        "13",
        "17",
    }, f"Missing: {set('9 10 12 13 17'.split()) - covered}"
