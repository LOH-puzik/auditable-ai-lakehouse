# Replay tool

The auditor replay tool reconstructs any past scoring decision and produces a structured evidence pack.

## Usage

```bash
# Replay a single alert
uv run replay --alert-id ALERT-SCORE-20260516100000-00000000

# Replay every event in a batch
uv run replay --batch-id BATCH-20260516100000

# Save the evidence pack
uv run replay --alert-id ALERT-SCORE-20260516100000-00000000 --output replay-report.json
```

The local prototype reads the same artifacts produced by notebooks 04-07. These paths can be overridden with environment variables: `SWIFT_AUDIT_GOLD_RECORDS`, `SWIFT_AUDIT_PROMOTION_MANIFEST`, `SWIFT_AUDIT_INFERENCE_EVENTS`, `SWIFT_AUDIT_ANCHOR_BATCHES_DIR`, and `SWIFT_AUDIT_ANCHOR_BATCH_MANIFEST`.

## Output

The tool emits a `ReplayReport` covering four named checks:

| Check | What it verifies |
|---|---|
| `input_hash_match` | The reconstructed feature row hashes to the value in the `InferenceEvent`. |
| `deterministic_score_match` | Re-scoring the model on the reconstructed input matches the logged score. |
| `merkle_proof_valid` | The stored inclusion proof reconstructs the batch root. |
| `onchain_root_match` | The batch root equals the root read back from the Aptos transaction. |

The report passes only if all four checks pass.

If the batch has not been anchored on Aptos, the first three checks can pass but `onchain_root_match` will fail because no external root exists yet.

## Standalone anchor verification

For integrity checks that don't need re-inference:

```bash
uv run verify-anchor --batch-id BATCH-20260516100000
uv run verify-anchor --batch-id BATCH-20260516100000 --output anchor-verification.json
```

This command checks local event membership, source event hashes, Merkle proof validity, and the Aptos root when the batch manifest contains a transaction hash.
