# Replay tool

The auditor replay tool reconstructs any past scoring decision and produces a structured evidence pack.

## Usage

```bash
# Replay a single alert
uv run replay --alert-id ALERT-2026-000123

# Replay every event in a batch
uv run replay --batch-id BATCH-2026-04-15-0001
```

## Output

The tool emits a `ReplayReport` covering four named checks:

| Check | What it verifies |
|---|---|
| `input_hash_match` | The reconstructed feature row hashes to the value in the `InferenceEvent`. |
| `deterministic_score_match` | Re-scoring the model on the reconstructed input matches the logged score. |
| `merkle_proof_valid` | The stored inclusion proof reconstructs the batch root. |
| `onchain_root_match` | The batch root equals the root read back from the Sepolia transaction. |

The report passes only if all four checks pass.

## Standalone anchor verification

For integrity checks that don't need re-inference:

```bash
uv run verify-anchor verify --batch-id BATCH-2026-04-15-0001
```
