"""Configuration loader.

Reads YAML config files and environment variables into a typed settings object.
Secrets (private keys, RPC tokens) come from env vars only — never from YAML.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class PathsConfig(BaseModel):
    """Storage paths for the medallion layers and governance event store."""

    bronze: str = "/Volumes/main/audit/bronze"
    silver: str = "/Volumes/main/audit/silver"
    silver_quarantine: str = "/Volumes/main/audit/silver_quarantine"
    gold: str = "/Volumes/main/audit/gold"
    governance_events: str = "/Volumes/main/audit/governance_events"


class MLflowConfig(BaseModel):
    """MLflow registry settings."""

    tracking_uri: str = "databricks"
    experiment_name: str = "/Shared/audit_lakehouse/isolation_forest"
    registered_model_name: str = "audit_lakehouse_isolation_forest"
    promotion_thresholds: dict[str, float] = Field(
        default_factory=lambda: {
            "precision": 0.80,
            "recall": 0.70,
            "precision_at_k": 0.85,
        }
    )


class AnchoringConfig(BaseModel):
    """Aptos anchoring settings. Private key comes from env var only."""

    node_url: str = "https://fullnode.testnet.aptoslabs.com/v1"
    faucet_url: str = "https://faucet.testnet.aptoslabs.com"
    account_address: str = ""
    module_address: str = ""
    module_name: str = "merkle_registry"
    function_name: str = "store_merkle_root"
    event_name: str = "MerkleRootStored"
    batch_size: int = 100  # events per Merkle batch
    max_gas_amount: int = 10_000
    gas_unit_price: int = 100


class GovernanceConfig(BaseModel):
    """Identities and approvers used as stand-ins for SSO in this prototype."""

    approver: str = "thesis_prototype_approver"
    deployer: str = "thesis_prototype_deployer"


class Settings(BaseSettings):
    """Top-level settings object."""

    model_config = SettingsConfigDict(
        env_prefix="AUDIT_LAKEHOUSE_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
    )

    environment: str = "dev"
    seed: int = 42
    paths: PathsConfig = Field(default_factory=PathsConfig)
    mlflow: MLflowConfig = Field(default_factory=MLflowConfig)
    anchoring: AnchoringConfig = Field(default_factory=AnchoringConfig)
    governance: GovernanceConfig = Field(default_factory=GovernanceConfig)

    # Secret: must come from env (AUDIT_LAKEHOUSE_ANCHORING_PRIVATE_KEY)
    anchoring_private_key: SecretStr = SecretStr("")


def load_settings(config_path: str | Path | None = None) -> Settings:
    """Load settings from a YAML file plus environment variables.

    Environment variables override YAML. Secrets are env-only.
    """
    overrides: dict[str, Any] = {}
    if config_path is not None:
        with open(config_path) as f:
            overrides = yaml.safe_load(f) or {}
    return Settings(**overrides)
