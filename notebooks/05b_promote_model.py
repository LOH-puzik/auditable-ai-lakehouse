# Databricks notebook source
# MAGIC %md
# MAGIC # 05b_promote_model
# MAGIC
# MAGIC This notebook is a placeholder. See the build plan in docs/architecture.md
# MAGIC for the implementation scope of this stage.

# COMMAND ----------
# MAGIC %pip install -e ../

# COMMAND ----------
from swift_audit.config import load_settings
settings = load_settings("../config/default.yaml")
print(settings.environment)
