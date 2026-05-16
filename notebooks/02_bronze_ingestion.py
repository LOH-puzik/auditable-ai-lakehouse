# Databricks notebook source
# MAGIC %md
# MAGIC # 02_bronze_ingestion
# MAGIC
# MAGIC Ingest raw synthetic SWIFT messages into the Bronze layer with immutable raw payloads.

# COMMAND ----------
# MAGIC %pip install -e ../

# COMMAND ----------
from __future__ import annotations

import os
from pathlib import Path

from audit_lakehouse.config import load_settings
from audit_lakehouse.lakehouse import ingest_bronze_raw_messages


def _repo_root() -> Path:
    current = Path.cwd()
    for candidate in [current, *current.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    return current


ROOT = _repo_root()
CONFIG_PATH = Path(os.getenv("AUDIT_LAKEHOUSE_CONFIG", str(ROOT / "config/default.yaml")))
SYNTHETIC_DIR = Path(
    os.getenv("AUDIT_LAKEHOUSE_SYNTHETIC_OUTPUT", str(ROOT / "data/raw/synthetic_swift"))
)
RAW_MESSAGES_PATH = Path(
    os.getenv("AUDIT_LAKEHOUSE_RAW_MESSAGES", str(SYNTHETIC_DIR / "raw_messages.jsonl"))
)
BRONZE_OUTPUT_DIR = Path(
    os.getenv("AUDIT_LAKEHOUSE_BRONZE_OUTPUT", str(ROOT / "data/bronze/swift_messages"))
)

settings = load_settings(CONFIG_PATH)
result = ingest_bronze_raw_messages(
    RAW_MESSAGES_PATH,
    BRONZE_OUTPUT_DIR,
)

print(f"environment={settings.environment}")
print(f"input_path={result.input_path}")
print(f"output_dir={result.output_dir}")
print(f"ingestion_batch_id={result.ingestion_batch_id}")
print(f"records_read={result.records_read}")
print(f"records_written={result.records_written}")
print(f"records={result.records_path}")
print(f"manifest={result.manifest_path}")
