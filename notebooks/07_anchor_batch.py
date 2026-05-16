# Databricks notebook source
# MAGIC %md
# MAGIC # 07_anchor_batch
# MAGIC
# MAGIC Build a Merkle batch from governance events and write inclusion proofs.

# COMMAND ----------
# MAGIC %pip install -e ../

# COMMAND ----------
from __future__ import annotations

import os
from pathlib import Path

from audit_lakehouse.anchoring import AptosLedgerClient, build_anchor_batch, finalize_anchor_batch
from audit_lakehouse.config import load_settings


def _repo_root() -> Path:
    current = Path.cwd()
    for candidate in [current, *current.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    return current


ROOT = _repo_root()
CONFIG_PATH = Path(os.getenv("AUDIT_LAKEHOUSE_CONFIG", str(ROOT / "config/default.yaml")))
GOVERNANCE_EVENTS_DIR = Path(
    os.getenv("AUDIT_LAKEHOUSE_GOVERNANCE_EVENTS_DIR", str(ROOT / "data/governance_events"))
)
ANCHOR_BATCH_OUTPUT_DIR = Path(
    os.getenv("AUDIT_LAKEHOUSE_ANCHOR_BATCH_OUTPUT", str(ROOT / "data/anchor_batches/latest"))
)
ANCHOR_EVENTS_PATH = Path(
    os.getenv(
        "AUDIT_LAKEHOUSE_ANCHOR_EVENTS",
        str(ROOT / "data/governance_events/anchor_events.jsonl"),
    )
)
ANCHOR_ONCHAIN = os.getenv("AUDIT_LAKEHOUSE_ANCHOR_ONCHAIN", "false").lower() in {
    "1",
    "true",
    "yes",
}
EVENT_PATHS = [
    GOVERNANCE_EVENTS_DIR / "quarantine_events.jsonl",
    GOVERNANCE_EVENTS_DIR / "promotion_events.jsonl",
    GOVERNANCE_EVENTS_DIR / "inference_events.jsonl",
]

settings = load_settings(CONFIG_PATH)
result = build_anchor_batch(
    EVENT_PATHS,
    ANCHOR_BATCH_OUTPUT_DIR,
)

print(f"environment={settings.environment}")
print(f"event_paths={[str(path) for path in result.event_paths]}")
print(f"output_dir={result.output_dir}")
print(f"batch_id={result.batch_id}")
print(f"merkle_root={result.merkle_root}")
print(f"leaf_count={result.leaf_count}")
print(f"events_path={result.events_path}")
print(f"proofs_path={result.proofs_path}")
print(f"manifest_path={result.manifest_path}")

if ANCHOR_ONCHAIN:
    private_key = settings.anchoring_private_key.get_secret_value()
    ledger = AptosLedgerClient(
        node_url=settings.anchoring.node_url,
        private_key=private_key,
        account_address=settings.anchoring.account_address,
        module_address=settings.anchoring.module_address,
        module_name=settings.anchoring.module_name,
        function_name=settings.anchoring.function_name,
        event_name=settings.anchoring.event_name,
        max_gas_amount=settings.anchoring.max_gas_amount,
        gas_unit_price=settings.anchoring.gas_unit_price,
    )
    onchain = finalize_anchor_batch(
        result.manifest_path,
        ledger,
        ANCHOR_EVENTS_PATH,
    )
    print("onchain_anchor=true")
    print(f"tx_hash={onchain.tx_hash}")
    print(f"block_number={onchain.block_number}")
    print(f"anchor_events_path={onchain.governance_events_path}")
else:
    print("onchain_anchor=false")
