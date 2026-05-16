# Architecture

This page expands the three pillars summarised on the home page and walks through each artefact in implementation order.

> **Status:** prototype implementation. The core pipeline, model lifecycle, Merkle batching, Aptos anchoring adapter, and replay tool are implemented; the standalone `verify-anchor` command remains separate work.

## Build order

1. **Synthetic SWIFT generator** (`src/swift_audit/generator/`) — produces MT540 and MT548 messages with controlled, labelled anomaly injection.
2. **Bronze / Silver / Gold pipeline** (`notebooks/02-04_*.py`) — ingestion, structural validation with a quarantine table, feature engineering with snapshot identifiers.
3. **MLflow lifecycle** (`notebooks/05_*.py`, `notebooks/05b_*.py`) — Isolation Forest training, registry promotion gated on precision / recall / precision@k, governance-event emission on promotion.
4. **Scoring + governance events** (`notebooks/06_*.py`) — score the Gold layer and emit `InferenceEvent` records.
5. **Merkle anchoring** (`src/swift_audit/anchoring/`, `notebooks/07_*.py`) — batch events, build the Merkle tree, anchor the root to Aptos, emit `AnchorEvent`.
6. **Replay tool** (`src/swift_audit/replay/`) — Typer CLI that reconstructs, re-scores, and verifies.
7. **Compliance rendering** (`src/swift_audit/compliance/`) — generates this site's compliance page from the YAML source.
