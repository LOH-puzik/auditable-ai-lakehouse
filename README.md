# auditable-ai-lakehouse

An auditable AI architecture for post-trade financial operations, designed to be **audit-ready by design** rather than audit-ready as an afterthought.

This repository accompanies an MSc thesis exploring how a medallion lakehouse architecture, MLflow model versioning, and blockchain-anchored audit logs can together enable AI systems that meet the evidential requirements of the EU AI Act (Regulation EU 2024/1689) and adjacent regulations (BCBS 239, EBA model-risk guidance, GDPR).

## The three pillars

1. **Medallion lakehouse** — Bronze (raw SWIFT-like MT540/MT548 ingestion), Silver (parsed + structurally validated, with a quarantine table for non-conforming records), Gold (feature engineering with snapshot identifiers for reproducibility). Implemented on Databricks and Delta Lake.
2. **MLflow model lifecycle** — an Isolation Forest anomaly-detection model trained, versioned, and promoted through formal staging gates. Promotion from Staging to Production is conditional on metric thresholds (precision, recall, precision@k) and each promotion event is logged to the governance event store.
3. **Blockchain-anchored audit log** — full governance events remain in Delta Lake, but cryptographic hashes of batches are aggregated into Merkle trees whose roots are committed to an external append-only ledger. This prototype uses Aptos devnet as a low-friction proxy for a permissioned enterprise ledger.

An **auditor replay tool** closes the loop: given an alert or batch identifier, the tool reloads the exact Gold snapshot, re-runs inference deterministically, compares the result to the logged output, and verifies the Merkle inclusion proof against the anchored root.

## Repository layout

```
auditable-ai-lakehouse/
├── notebooks/         Databricks notebooks (Bronze → Silver → Gold → train → score → anchor)
├── src/swift_audit/   Installable Python package (generator, anchoring, replay, compliance)
├── tests/             Unit tests (pytest)
├── config/            YAML configuration (local demo, default gates, Aptos devnet)
├── docs/              MkDocs site (architecture, compliance mapping, replay tool)
├── scripts/           Convenience shell scripts
└── .github/workflows/ CI (pytest + ruff) and docs deployment
```

## Quickstart

### Prerequisites
- Python 3.11
- [uv](https://github.com/astral-sh/uv) for dependency management
- A Databricks Free Edition account (for running the notebooks)
- An Aptos devnet account and the Aptos CLI (only needed for on-chain anchoring)

### Install
```bash
git clone https://github.com/LOH-puzik/auditable-ai-lakehouse.git
cd auditable-ai-lakehouse
uv sync
```

### Local environment

This project can be installed with `uv` or with a standard Python virtual environment.

#### Option A: using uv

```bash
uv sync --extra dev --extra docs
uv run pytest -q
```

#### Option B: using venv

On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev,docs]"
python -m pytest -q
```

On macOS/Linux:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev,docs]"
python -m pytest -q
```

When returning to the project, reactivate the environment first:

```powershell
.\.venv\Scripts\Activate.ps1
```

### Run tests
```bash
uv run pytest
```

### Run the full demo pipeline

The simplest end-to-end demo is the orchestrator executable. It creates a new run under `data/runs/<RUN_ID>/`, then writes a `run_manifest.json` that the replay menu can discover later. The short commands are `run` and `replay-menu`; the same entry points are also available as `swift-audit-run` and `swift-audit-replay-menu`.

```powershell
.\.venv\Scripts\run.exe --n 100 --seed 42 --anomaly-rate 0.08
```

This runs synthetic ingestion, Bronze/Silver/Gold processing, model training, promotion, scoring, governance event generation, and local Merkle batching.

The executable defaults to `config/local-demo.yaml`, which keeps promotion thresholds permissive so small synthetic demos complete. Use `--config config/default.yaml` when you want the stricter thesis governance gates.

After a run, choose an event interactively and replay it:

```powershell
.\.venv\Scripts\replay-menu.exe
```

To choose without the prompt:

```powershell
.\.venv\Scripts\replay-menu.exe --index 0
```

### Run the replay tool
```bash
uv run replay --alert-id <ALERT_ID>
# or
uv run replay --batch-id <BATCH_ID>
```

### Optional Aptos anchoring

The local Merkle batch runs without a blockchain account. To publish roots to Aptos devnet, install the Aptos CLI, initialize/fund a devnet account, publish the Move module once, then run stage 07 with on-chain anchoring enabled:

```powershell
aptos init --network devnet
aptos move publish --package-dir move/audit_anchor --named-addresses audit_anchor=<YOUR_APTOS_ADDRESS>

$env:SWIFT_AUDIT_CONFIG="config/aptos-devnet.yaml"
$env:SWIFT_AUDIT_ANCHORING_PRIVATE_KEY="0x..."
$env:SWIFT_AUDIT_ANCHORING__MODULE_ADDRESS="<YOUR_APTOS_ADDRESS>"
$env:SWIFT_AUDIT_ANCHOR_ONCHAIN="true"
.\.venv\Scripts\python.exe notebooks\07_anchor_batch.py
```

The orchestrator can also submit the Merkle root once the Aptos account and Move module are ready:

```powershell
$env:SWIFT_AUDIT_CONFIG="config/aptos-devnet.yaml"
$env:SWIFT_AUDIT_ANCHORING_PRIVATE_KEY="0x..."
$env:SWIFT_AUDIT_ANCHORING__ACCOUNT_ADDRESS="<YOUR_APTOS_ADDRESS>"
$env:SWIFT_AUDIT_ANCHORING__MODULE_ADDRESS="<YOUR_APTOS_ADDRESS>"

.\.venv\Scripts\run.exe --onchain
```

## Documentation

Full documentation, including the architecture deep-dive and the compliance mapping, is published via MkDocs. To build locally:
```bash
uv run mkdocs serve
```

## Citing this work

If you use this repository in academic work, please cite it via the metadata in `CITATION.cff`.

## License

This project is licensed under **AGPL-3.0-or-later**. See [LICENSE](LICENSE) for details. Commercial use that does not comply with the AGPL's network-copyleft provisions is not permitted.
