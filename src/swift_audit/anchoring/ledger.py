"""Ledger abstraction.

The thesis treats the public Aptos devnet/testnet as a practical proxy for an
external append-only audit domain. The rest of the system talks to a
`LedgerClient` protocol rather than to an Aptos SDK client directly, so a
permissioned ledger adapter can still be swapped in later.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AnchorReceipt:
    """The result of anchoring a Merkle root on a ledger."""

    tx_hash: str
    block_number: int
    merkle_root: str


class LedgerClient(Protocol):
    """Minimal interface for any append-only ledger used as an anchor target."""

    def commit_root(self, merkle_root: str) -> AnchorReceipt:
        """Submit a Merkle root and return a receipt once it is included."""
        ...

    def read_root(self, tx_hash: str) -> str:
        """Read back the Merkle root that was committed in a given transaction."""
        ...
