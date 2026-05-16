# auditable-ai-lakehouse

An auditable AI architecture for post-trade financial operations, designed to be **audit-ready by design** rather than audit-ready as an afterthought.

This repository accompanies an MSc thesis exploring how a medallion lakehouse architecture, MLflow model versioning, and blockchain-anchored audit logs can together enable AI systems that meet the evidential requirements of the EU AI Act (Regulation EU 2024/1689) and adjacent regulations (BCBS 239, EBA model-risk guidance, GDPR).

## The three pillars

1. **Medallion lakehouse** — Bronze (raw SWIFT-like MT540/MT548 ingestion), Silver (parsed + structurally validated, with a quarantine table for non-conforming records), Gold (feature engineering with snapshot identifiers for reproducibility). Implemented on Databricks and Delta Lake.
2. **MLflow model lifecycle** — an Isolation Forest anomaly-detection model trained, versioned, and promoted through formal staging gates. Promotion from Staging to Production is conditional on metric thresholds (precision, recall, precision@k) and each promotion event is logged to the governance event store.
3. **Blockchain-anchored audit log** — full governance events remain in Delta Lake, but cryptographic hashes of batches are aggregated into Merkle trees whose roots are committed to an external append-only ledger. This prototype uses Aptos testnet as a low-friction proxy for a permissioned enterprise ledger.

An **auditor replay tool** closes the loop: given an alert or batch identifier, the tool reloads the exact Gold snapshot, re-runs inference deterministically, compares the result to the logged output, and verifies the Merkle inclusion proof against the anchored root.

## Repository layout

```
auditable-ai-lakehouse/
├── blockchain/          Aptos Move package for Merkle root anchoring
├── notebooks/           Databricks notebooks (Bronze → Silver → Gold → train → score → anchor)
├── src/audit_lakehouse/ Installable Python package (generator, anchoring, replay, compliance)
├── tests/               Unit tests (pytest)
├── config/              YAML configuration (local demo, default gates, Aptos testnet)
├── docs/                MkDocs site (architecture, compliance mapping, replay tool)
├── scripts/             Convenience shell scripts
└── .github/workflows/   CI (pytest + ruff) and docs deployment
```

## Quickstart

### Prerequisites
- Python 3.11
- [uv](https://github.com/astral-sh/uv) for dependency management
- A Databricks Free Edition account (for running the notebooks)
- An Aptos testnet account and the Aptos CLI (only needed for on-chain anchoring)

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

The simplest end-to-end demo is the orchestrator executable. It creates a new run under `data/runs/<RUN_ID>/`, then writes a `run_manifest.json` that the replay menu can discover later. The short commands are `run` and `replay-menu`; the same entry points are also available as `audit-lakehouse-run` and `audit-lakehouse-replay-menu`.

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

Before Aptos anchoring is configured, local replay can still prove the input hash, deterministic score, and Merkle proof. Use this for local smoke tests:

```powershell
.\.venv\Scripts\replay-menu.exe --index 0 --allow-unanchored
```

### Run the replay tool
```bash
uv run replay --alert-id <ALERT_ID>
# or
uv run replay --batch-id <BATCH_ID>
```

### Aptos anchoring demo

For the full thesis demo, publish the Move package once, set the Aptos environment variables once, then `run.exe` will publish each new Merkle root to Aptos automatically.

```powershell
aptos init --profile audit-lakehouse-testnet --network testnet
aptos move publish --profile audit-lakehouse-testnet --package-dir blockchain --named-addresses auditable_ai_lakehouse=<YOUR_APTOS_ADDRESS>
```

For a repeatable local demo, create `.env` from `.env.example` and fill in the testnet values. The real `.env` is gitignored.

```powershell
Copy-Item .env.example .env
```

The relevant values are:

```powershell
$env:AUDIT_LAKEHOUSE_CONFIG="config/aptos-testnet.yaml"
$env:AUDIT_LAKEHOUSE_ANCHORING__ACCOUNT_ADDRESS="<YOUR_APTOS_ADDRESS>"
$env:AUDIT_LAKEHOUSE_ANCHORING__MODULE_ADDRESS="<YOUR_APTOS_ADDRESS>"
$env:AUDIT_LAKEHOUSE_ANCHOR_ONCHAIN="true"
```

Do not commit private keys. You can either set `AUDIT_LAKEHOUSE_ANCHORING_PRIVATE_KEY` in your local `.env`, or leave it unset and `run.exe` will ask for it when it needs to submit the Aptos transaction.

After those variables are set in PowerShell or saved in `.env`, the normal run command anchors on-chain and prints the Aptos Explorer transaction URL:

```powershell
.\.venv\Scripts\run.exe
```

Then replay without `--allow-unanchored`; the replay command also prints the same Explorer transaction URL:

```powershell
.\.venv\Scripts\replay-menu.exe --index 0
```

For offline local runs, force no chain submission with `--local-only`.

## Documentation

Full documentation, including the architecture deep-dive and the compliance mapping, is published via MkDocs. To build locally:
```bash
uv run mkdocs serve
```

## Citing this work

If you use this repository in academic work, please cite it via the metadata in `CITATION.cff`.

## License

This project is licensed under **AGPL-3.0-or-later**. See [LICENSE](LICENSE) for details. Commercial use that does not comply with the AGPL's network-copyleft provisions is not permitted.
