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

### Run the full project end to end

Use this sequence for the thesis demo on Windows PowerShell.

#### First-time setup

Clone the repository and create the local Python environment:

```powershell
git clone https://github.com/LOH-puzik/auditable-ai-lakehouse.git
cd auditable-ai-lakehouse
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev,docs]"
```

Publish the Aptos Move module once:

```powershell
aptos init --profile audit-lakehouse-testnet --network testnet
aptos move compile --package-dir blockchain --named-addresses auditable_ai_lakehouse=<YOUR_APTOS_ADDRESS>
aptos move publish --profile audit-lakehouse-testnet --package-dir blockchain --named-addresses auditable_ai_lakehouse=<YOUR_APTOS_ADDRESS>
```

Create a local `.env` file. The real `.env` is gitignored:

```powershell
New-Item -Path .env -ItemType File -Force
```

Set these values in `.env`:

```text
AUDIT_LAKEHOUSE_CONFIG=config/aptos-testnet.yaml
AUDIT_LAKEHOUSE_ANCHOR_ONCHAIN=true
AUDIT_LAKEHOUSE_ANCHORING__ACCOUNT_ADDRESS=<YOUR_APTOS_ADDRESS>
AUDIT_LAKEHOUSE_ANCHORING__MODULE_ADDRESS=<YOUR_APTOS_ADDRESS>
AUDIT_LAKEHOUSE_ANCHORING_PRIVATE_KEY=<YOUR_APTOS_PRIVATE_KEY>
```

Do not commit private keys. Keep `.env` local only.

#### Fresh demo run

Every fresh demo run uses three commands.

1. Activate the environment:

```powershell
cd C:\Users\Dhia\Projects\MSc-thesis\auditable-ai-lakehouse
.\.venv\Scripts\Activate.ps1
```

2. Run the pipeline and anchor the Merkle root on Aptos testnet:

```powershell
.\.venv\Scripts\run.exe 2>&1 | Tee-Object run_output.txt
```

3. Replay the newest event and verify the audit chain:

```powershell
.\.venv\Scripts\replay-menu.exe --index 0 2>&1 | Tee-Object replay_output.txt
```

Optional reliability check:

```powershell
.\.venv\Scripts\python.exe -m pytest -q 2>&1 | Tee-Object pytest_output.txt
```

#### Output fields

`run.exe` prints one table for the new pipeline execution:

| Field | Meaning |
| --- | --- |
| `run_id` | Unique identifier for this full execution. |
| `run_dir` | Local folder containing the generated manifests and artifacts. |
| `records_generated` | Number of synthetic input records created. |
| `records_scored` | Number of records scored by the model. |
| `alerts_generated` | Number of records classified as alerts. |
| `batch_id` | Identifier of the Merkle batch created from the governance events. |
| `merkle_root` | Cryptographic root summarizing the event batch. |
| `onchain_anchor` | Whether the Merkle root was written to Aptos. |
| `tx_hash` | Aptos transaction ID. Paste this into Aptos Explorer on testnet. |
| `aptos_explorer` | Direct Aptos Explorer URL for the transaction. |
| `manifest` | Main JSON summary for the run. |

`replay-menu.exe --index 0` first lists replayable events, then prints one JSON report:

| Field | Meaning |
| --- | --- |
| `alert_id` | Event selected for replay. |
| `batch_id` | Merkle batch containing the event. |
| `input_hash_match` | Recomputed model input hash matches the logged input hash. |
| `deterministic_score_match` | Recomputed model score matches the logged score. |
| `merkle_proof_valid` | The event is included in the Merkle batch. |
| `onchain_root_match` | Local Merkle root matches the root stored on Aptos. |
| `passed` | Overall audit result. This should be `true` for a valid replay. |
| `tx_hash` | Aptos transaction ID used for the on-chain root check. |

#### Optional local-only smoke test

For a demo without Aptos submission:

```powershell
.\.venv\Scripts\run.exe --local-only
.\.venv\Scripts\replay-menu.exe --index 0 --allow-unanchored
```

### Run the replay tool directly
```bash
uv run replay --alert-id <ALERT_ID>
# or
uv run replay --batch-id <BATCH_ID>
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
