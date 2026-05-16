# Databricks notebook source
# MAGIC %md
# MAGIC # 05b_promote_model
# MAGIC
# MAGIC Promote the trained Isolation Forest if configured metric gates pass.

# COMMAND ----------
# MAGIC %pip install -e ../

# COMMAND ----------
from __future__ import annotations

import os
from pathlib import Path

from audit_lakehouse.config import load_settings
from audit_lakehouse.modeling import promote_model


def _repo_root() -> Path:
    current = Path.cwd()
    for candidate in [current, *current.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    return current


ROOT = _repo_root()
CONFIG_PATH = Path(os.getenv("AUDIT_LAKEHOUSE_CONFIG", str(ROOT / "config/default.yaml")))
TRAINING_MANIFEST_PATH = Path(
    os.getenv(
        "AUDIT_LAKEHOUSE_TRAINING_MANIFEST",
        str(ROOT / "data/models/isolation_forest/manifest.json"),
    )
)
PROMOTION_OUTPUT_DIR = Path(
    os.getenv(
        "AUDIT_LAKEHOUSE_PROMOTION_OUTPUT",
        str(ROOT / "data/model_registry/production/isolation_forest"),
    )
)
PROMOTION_EVENTS_PATH = Path(
    os.getenv(
        "AUDIT_LAKEHOUSE_PROMOTION_EVENTS",
        str(ROOT / "data/governance_events/promotion_events.jsonl"),
    )
)

settings = load_settings(CONFIG_PATH)
result = promote_model(
    TRAINING_MANIFEST_PATH,
    PROMOTION_OUTPUT_DIR,
    PROMOTION_EVENTS_PATH,
    model_name=settings.mlflow.registered_model_name,
    thresholds=settings.mlflow.promotion_thresholds,
    approver=settings.governance.approver,
)

print(f"environment={settings.environment}")
print(f"training_manifest_path={result.training_manifest_path}")
print(f"output_dir={result.output_dir}")
print(f"promotion_id={result.promotion_id}")
print(f"approved={result.approved}")
print(f"gate_results={result.gate_results}")
print(f"event_written={result.event_written}")
print(f"manifest_path={result.manifest_path}")
print(f"promoted_model_path={result.promoted_model_path}")
print(f"governance_events_path={result.governance_events_path}")
