"""Replay report.

Per the thesis commitment, the report exposes the four named checks that
Chapter 1 describes the replay tool as performing:

  1. input_hash_match           - the reconstructed feature row hashes to the
                                  value recorded in the InferenceEvent.
  2. deterministic_score_match  - the re-scored output equals the logged score.
  3. merkle_proof_valid         - the stored proof reconstructs the batch root.
  4. onchain_root_match         - the batch root equals the root on-chain.

The whole report PASSES only if all four checks pass.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ReplayReport:
    alert_id: str
    batch_id: str
    input_hash_match: bool
    deterministic_score_match: bool
    merkle_proof_valid: bool
    onchain_root_match: bool

    # Evidence values for the auditor (not used in the pass/fail computation)
    logged_input_hash: str
    recomputed_input_hash: str
    logged_score: float
    recomputed_score: float
    merkle_root: str
    onchain_root: str
    tx_hash: str

    @property
    def passed(self) -> bool:
        return (
            self.input_hash_match
            and self.deterministic_score_match
            and self.merkle_proof_valid
            and self.onchain_root_match
        )

    def to_json(self) -> str:
        return json.dumps({"passed": self.passed, **asdict(self)}, indent=2)
