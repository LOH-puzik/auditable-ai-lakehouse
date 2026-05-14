"""Sepolia anchoring: writes Merkle roots into the `data` field of an EOA-to-self
transaction. No smart contract is required — the root is preserved verbatim on
the chain and can be read back from the transaction receipt.

This choice keeps the system minimal: no Solidity, no contract deployment, no
ABI versioning. The trade-off is that we can't index roots on-chain — but for an
audit trail that's fine, because the off-chain governance event store maintains
the (tx_hash -> root) index.
"""

from __future__ import annotations

from swift_audit.anchoring.ledger import AnchorReceipt, LedgerClient


class SepoliaLedgerClient(LedgerClient):
    """LedgerClient implementation backed by the Sepolia public testnet."""

    def __init__(
        self,
        rpc_url: str,
        private_key: str,
        wallet_address: str,
        chain_id: int = 11155111,
        gas_limit: int = 100_000,
    ) -> None:
        self.rpc_url = rpc_url
        self.private_key = private_key
        self.wallet_address = wallet_address
        self.chain_id = chain_id
        self.gas_limit = gas_limit

    def commit_root(self, merkle_root: str) -> AnchorReceipt:
        raise NotImplementedError("Implement in step 5 of the build plan")

    def read_root(self, tx_hash: str) -> str:
        raise NotImplementedError("Implement in step 5 of the build plan")
