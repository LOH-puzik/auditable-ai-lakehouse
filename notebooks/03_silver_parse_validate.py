# Databricks notebook source
# MAGIC %md
# MAGIC # 03_silver_parse_validate
# MAGIC
# MAGIC Parse Bronze MT540/MT548 raw messages into Silver records and quarantine invalid rows.

# COMMAND ----------
# MAGIC %pip install -e ../

# COMMAND ----------
from __future__ import annotations

import os
from pathlib import Path

from audit_lakehouse.config import load_settings
from audit_lakehouse.lakehouse import parse_validate_silver


def _repo_root() -> Path:
    current = Path.cwd()
    for candidate in [current, *current.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    return current


ROOT = _repo_root()
CONFIG_PATH = Path(os.getenv("AUDIT_LAKEHOUSE_CONFIG", str(ROOT / "config/default.yaml")))
BRONZE_RECORDS_PATH = Path(
    os.getenv(
        "AUDIT_LAKEHOUSE_BRONZE_RECORDS", str(ROOT / "data/bronze/swift_messages/records.jsonl")
    )
)
SILVER_OUTPUT_DIR = Path(
    os.getenv("AUDIT_LAKEHOUSE_SILVER_OUTPUT", str(ROOT / "data/silver/swift_messages"))
)
QUARANTINE_OUTPUT_DIR = Path(
    os.getenv(
        "AUDIT_LAKEHOUSE_SILVER_QUARANTINE_OUTPUT",
        str(ROOT / "data/silver_quarantine/swift_messages"),
    )
)
GOVERNANCE_EVENTS_PATH = Path(
    os.getenv(
        "AUDIT_LAKEHOUSE_QUARANTINE_EVENTS",
        str(ROOT / "data/governance_events/quarantine_events.jsonl"),
    )
)

settings = load_settings(CONFIG_PATH)
result = parse_validate_silver(
    BRONZE_RECORDS_PATH,
    SILVER_OUTPUT_DIR,
    QUARANTINE_OUTPUT_DIR,
    GOVERNANCE_EVENTS_PATH,
)

print(f"environment={settings.environment}")
print(f"input_path={result.input_path}")
print(f"silver_output_dir={result.silver_output_dir}")
print(f"quarantine_output_dir={result.quarantine_output_dir}")
print(f"governance_events={result.governance_events_path}")
print(f"validation_batch_id={result.validation_batch_id}")
print(f"records_read={result.records_read}")
print(f"instructions_written={result.instructions_written}")
print(f"statuses_written={result.statuses_written}")
print(f"quarantined={result.quarantined}")
print(f"quarantine_events_written={result.quarantine_events_written}")
