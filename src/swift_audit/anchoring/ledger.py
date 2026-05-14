"""Ledger abstraction.

The thesis frames Sepolia as a proxy for a permissioned enterprise ledger such
as Hyperledger Fabric. To make that argument defensible, the rest of the system
talks to a `LedgerClient` protocol rather than to web3.py directly; swapping in
a Fabric client is then a localized change.
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
