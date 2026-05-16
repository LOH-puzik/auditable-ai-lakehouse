# Databricks notebook source
# MAGIC %md
# MAGIC # 05_train_isolation_forest
# MAGIC
# MAGIC Train and evaluate an Isolation Forest from Gold feature rows.

# COMMAND ----------
# MAGIC %pip install -e ../

# COMMAND ----------
from __future__ import annotations

import os
from pathlib import Path

from audit_lakehouse.config import load_settings
from audit_lakehouse.modeling import train_isolation_forest


def _repo_root() -> Path:
    current = Path.cwd()
    for candidate in [current, *current.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    return current


def _local_tracking_uri(root: Path) -> str:
    return (root / "data/mlruns").resolve().as_uri()


ROOT = _repo_root()
CONFIG_PATH = Path(os.getenv("AUDIT_LAKEHOUSE_CONFIG", str(ROOT / "config/default.yaml")))
GOLD_RECORDS_PATH = Path(
    os.getenv("AUDIT_LAKEHOUSE_GOLD_RECORDS", str(ROOT / "data/gold/features/records.jsonl"))
)
MODEL_OUTPUT_DIR = Path(
    os.getenv("AUDIT_LAKEHOUSE_MODEL_OUTPUT", str(ROOT / "data/models/isolation_forest"))
)
CONTAMINATION = float(os.getenv("AUDIT_LAKEHOUSE_IFOREST_CONTAMINATION", "0.05"))
N_ESTIMATORS = int(os.getenv("AUDIT_LAKEHOUSE_IFOREST_N_ESTIMATORS", "200"))

settings = load_settings(CONFIG_PATH)
tracking_uri = os.getenv("AUDIT_LAKEHOUSE_MLFLOW_TRACKING_URI", _local_tracking_uri(ROOT))
experiment_name = os.getenv("AUDIT_LAKEHOUSE_MLFLOW_EXPERIMENT", "audit_lakehouse/isolation_forest")

result = train_isolation_forest(
    GOLD_RECORDS_PATH,
    MODEL_OUTPUT_DIR,
    tracking_uri=tracking_uri,
    experiment_name=experiment_name,
    seed=settings.seed,
    contamination=CONTAMINATION,
    n_estimators=N_ESTIMATORS,
)

print(f"environment={settings.environment}")
print(f"gold_records_path={result.gold_records_path}")
print(f"output_dir={result.output_dir}")
print(f"training_run_id={result.training_run_id}")
print(f"rows_read={result.rows_read}")
print(f"feature_count={len(result.feature_columns)}")
print(f"mlflow_run_id={result.mlflow_run_id}")
print(f"mlflow_model_uri={result.mlflow_model_uri}")
print(f"model_path={result.model_path}")
print(f"metrics_path={result.metrics_path}")
print(f"predictions_path={result.predictions_path}")
print(f"manifest_path={result.manifest_path}")
for name, value in result.metrics.items():
    print(f"{name}={value}")
