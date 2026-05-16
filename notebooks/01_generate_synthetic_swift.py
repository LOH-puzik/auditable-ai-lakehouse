# Databricks notebook source
# MAGIC %md
# MAGIC # 01_generate_synthetic_swift
# MAGIC
# MAGIC Generate deterministic, labelled MT540/MT548 synthetic data for Bronze ingestion.

# COMMAND ----------
# MAGIC %pip install -e ../

# COMMAND ----------
from __future__ import annotations

import os
from pathlib import Path

from swift_audit.config import load_settings
from swift_audit.generator import generate_synthetic_swift_dataset


def _repo_root() -> Path:
    current = Path.cwd()
    for candidate in [current, *current.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    return current


ROOT = _repo_root()
CONFIG_PATH = Path(os.getenv("SWIFT_AUDIT_CONFIG", str(ROOT / "config/default.yaml")))
OUTPUT_DIR = Path(os.getenv("SWIFT_AUDIT_SYNTHETIC_OUTPUT", str(ROOT / "data/raw/synthetic_swift")))
RECORD_COUNT = int(os.getenv("SWIFT_AUDIT_SYNTHETIC_N", "1000"))
ANOMALY_RATE = float(os.getenv("SWIFT_AUDIT_ANOMALY_RATE", "0.02"))

settings = load_settings(CONFIG_PATH)

dataset = generate_synthetic_swift_dataset(
    RECORD_COUNT,
    seed=settings.seed,
    anomaly_rate=ANOMALY_RATE,
)
paths = dataset.write_jsonl(OUTPUT_DIR)

print(f"environment={settings.environment}")
print(f"seed={settings.seed}")
print(f"instructions={dataset.manifest['instruction_count']}")
print(f"statuses={dataset.manifest['status_count']}")
print(f"raw_messages={dataset.manifest['raw_message_count']}")
print(f"output_dir={OUTPUT_DIR}")
for name, path in paths.items():
    print(f"{name}={path}")
