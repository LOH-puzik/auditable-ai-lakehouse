# Databricks notebook source
# MAGIC %md
# MAGIC # 04_gold_features
# MAGIC
# MAGIC Build model-ready Gold features from validated Silver instructions and statuses.

# COMMAND ----------
# MAGIC %pip install -e ../

# COMMAND ----------
from __future__ import annotations

import os
from pathlib import Path

from audit_lakehouse.config import load_settings
from audit_lakehouse.lakehouse import build_gold_features


def _repo_root() -> Path:
    current = Path.cwd()
    for candidate in [current, *current.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    return current


ROOT = _repo_root()
CONFIG_PATH = Path(os.getenv("AUDIT_LAKEHOUSE_CONFIG", str(ROOT / "config/default.yaml")))
SILVER_INSTRUCTIONS_PATH = Path(
    os.getenv(
        "AUDIT_LAKEHOUSE_SILVER_INSTRUCTIONS",
        str(ROOT / "data/silver/swift_messages/instructions.jsonl"),
    )
)
SILVER_STATUSES_PATH = Path(
    os.getenv(
        "AUDIT_LAKEHOUSE_SILVER_STATUSES",
        str(ROOT / "data/silver/swift_messages/statuses.jsonl"),
    )
)
GOLD_OUTPUT_DIR = Path(os.getenv("AUDIT_LAKEHOUSE_GOLD_OUTPUT", str(ROOT / "data/gold/features")))

settings = load_settings(CONFIG_PATH)
result = build_gold_features(
    SILVER_INSTRUCTIONS_PATH,
    SILVER_STATUSES_PATH,
    GOLD_OUTPUT_DIR,
)

print(f"environment={settings.environment}")
print(f"instructions_path={result.instructions_path}")
print(f"statuses_path={result.statuses_path}")
print(f"output_dir={result.output_dir}")
print(f"gold_snapshot_id={result.gold_snapshot_id}")
print(f"records_read_instructions={result.records_read_instructions}")
print(f"records_read_statuses={result.records_read_statuses}")
print(f"features_written={result.features_written}")
print(f"records={result.records_path}")
print(f"manifest={result.manifest_path}")
