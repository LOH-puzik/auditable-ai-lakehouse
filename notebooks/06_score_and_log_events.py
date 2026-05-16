# Databricks notebook source
# MAGIC %md
# MAGIC # 06_score_and_log_events
# MAGIC
# MAGIC Score Gold feature rows with the promoted model and emit InferenceEvent records.

# COMMAND ----------
# MAGIC %pip install -e ../

# COMMAND ----------
from __future__ import annotations

import os
from pathlib import Path

from audit_lakehouse.config import load_settings
from audit_lakehouse.modeling import score_gold_features


def _repo_root() -> Path:
    current = Path.cwd()
    for candidate in [current, *current.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    return current


ROOT = _repo_root()
CONFIG_PATH = Path(os.getenv("AUDIT_LAKEHOUSE_CONFIG", str(ROOT / "config/default.yaml")))
GOLD_RECORDS_PATH = Path(
    os.getenv("AUDIT_LAKEHOUSE_GOLD_RECORDS", str(ROOT / "data/gold/features/records.jsonl"))
)
PROMOTION_MANIFEST_PATH = Path(
    os.getenv(
        "AUDIT_LAKEHOUSE_PROMOTION_MANIFEST",
        str(ROOT / "data/model_registry/production/isolation_forest/manifest.json"),
    )
)
SCORING_OUTPUT_DIR = Path(
    os.getenv("AUDIT_LAKEHOUSE_SCORING_OUTPUT", str(ROOT / "data/scoring/inference"))
)
INFERENCE_EVENTS_PATH = Path(
    os.getenv(
        "AUDIT_LAKEHOUSE_INFERENCE_EVENTS",
        str(ROOT / "data/governance_events/inference_events.jsonl"),
    )
)

settings = load_settings(CONFIG_PATH)
result = score_gold_features(
    GOLD_RECORDS_PATH,
    PROMOTION_MANIFEST_PATH,
    SCORING_OUTPUT_DIR,
    INFERENCE_EVENTS_PATH,
)

print(f"environment={settings.environment}")
print(f"gold_records_path={result.gold_records_path}")
print(f"promotion_manifest_path={result.promotion_manifest_path}")
print(f"output_dir={result.output_dir}")
print(f"scoring_batch_id={result.scoring_batch_id}")
print(f"records_read={result.records_read}")
print(f"records_scored={result.records_scored}")
print(f"events_written={result.events_written}")
print(f"alerts_generated={result.alerts_generated}")
print(f"scored_records_path={result.scored_records_path}")
print(f"governance_events_path={result.governance_events_path}")
print(f"manifest_path={result.manifest_path}")
