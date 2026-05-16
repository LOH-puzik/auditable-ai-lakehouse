"""Tests for Aptos ledger transaction construction without network access."""

from __future__ import annotations

import pytest

from audit_lakehouse.anchoring import AptosLedgerClient


def test_aptos_ledger_commits_root_and_reads_root_with_fake_client(monkeypatch) -> None:
    root = "a" * 64
    fake_client = _FakeAptosClient(root=root, event_address="0x" + "3" * 64)
    fake_account = _FakeAptosAccount("0x" + "2" * 64)
    monkeypatch.setattr(
        "audit_lakehouse.anchoring.anchor._build_anchor_payload",
        _fake_build_payload,
    )
    client = AptosLedgerClient(
        node_url="https://fullnode.testnet.aptoslabs.com/v1",
        private_key="0x" + "1" * 64,
        module_address="0x" + "3" * 64,
        aptos_client=fake_client,
        aptos_account=fake_account,
    )

    receipt = client.commit_root(root)

    assert receipt.tx_hash == "0x" + "4" * 64
    assert receipt.block_number == 456
    assert receipt.merkle_root == root
    assert fake_client.last_payload == {
        "module": "0x" + "3" * 64,
        "module_name": "merkle_registry",
        "function_name": "store_merkle_root",
        "root": root,
    }
    assert client.read_root(receipt.tx_hash) == root


def test_aptos_ledger_accepts_vector_root_from_event(monkeypatch) -> None:
    root = "b" * 64
    fake_client = _FakeAptosClient(
        root=[int(root[index : index + 2], 16) for index in range(0, 64, 2)],
        event_address="0x" + "2" * 64,
    )
    fake_account = _FakeAptosAccount("0x" + "2" * 64)
    monkeypatch.setattr(
        "audit_lakehouse.anchoring.anchor._build_anchor_payload",
        _fake_build_payload,
    )
    client = AptosLedgerClient(
        node_url="https://fullnode.testnet.aptoslabs.com/v1",
        private_key="0x" + "1" * 64,
        aptos_client=fake_client,
        aptos_account=fake_account,
    )

    assert client.read_root("0x" + "4" * 64) == root


def test_aptos_ledger_rejects_invalid_merkle_root(monkeypatch) -> None:
    fake_client = _FakeAptosClient(root="a" * 64)
    fake_account = _FakeAptosAccount("0x" + "2" * 64)
    monkeypatch.setattr(
        "audit_lakehouse.anchoring.anchor._build_anchor_payload",
        _fake_build_payload,
    )
    client = AptosLedgerClient(
        node_url="https://fullnode.testnet.aptoslabs.com/v1",
        private_key="0x" + "1" * 64,
        aptos_client=fake_client,
        aptos_account=fake_account,
    )

    with pytest.raises(ValueError, match="32-byte Merkle root"):
        client.commit_root("not-a-root")


def test_aptos_ledger_supports_read_only_root_lookup() -> None:
    root = "c" * 64
    client = AptosLedgerClient(
        node_url="https://fullnode.testnet.aptoslabs.com/v1",
        module_address="0x" + "2" * 64,
        aptos_client=_FakeAptosClient(root=root),
    )

    assert client.read_root("0x" + "4" * 64) == root


def test_aptos_ledger_rejects_missing_commit_key() -> None:
    fake_account = _FakeAptosAccount("0x" + "2" * 64)

    client = AptosLedgerClient(
        node_url="https://fullnode.testnet.aptoslabs.com/v1",
        aptos_client=_FakeAptosClient(root="a" * 64),
    )
    with pytest.raises(ValueError, match="private_key"):
        client.commit_root("a" * 64)

    with pytest.raises(ValueError, match="node_url"):
        AptosLedgerClient(
            node_url="",
            private_key="0x" + "1" * 64,
            aptos_client=_FakeAptosClient(root="a" * 64),
            aptos_account=fake_account,
        )


def test_aptos_ledger_rejects_missing_module_address_for_read_only() -> None:
    client = AptosLedgerClient(
        node_url="https://fullnode.testnet.aptoslabs.com/v1",
        aptos_client=_FakeAptosClient(root="a" * 64),
    )

    with pytest.raises(ValueError, match="module_address"):
        client.read_root("0x" + "4" * 64)


def test_aptos_ledger_rejects_account_mismatch() -> None:
    with pytest.raises(ValueError, match="account_address"):
        AptosLedgerClient(
            node_url="https://fullnode.testnet.aptoslabs.com/v1",
            private_key="0x" + "1" * 64,
            account_address="0x" + "3" * 64,
            aptos_client=_FakeAptosClient(root="a" * 64),
            aptos_account=_FakeAptosAccount("0x" + "2" * 64),
        )


def _fake_build_payload(
    *,
    module_address: str,
    module_name: str,
    function_name: str,
    root_bytes: bytes,
) -> dict:
    return {
        "module": module_address,
        "module_name": module_name,
        "function_name": function_name,
        "root": root_bytes.hex(),
    }


class _FakeAptosClient:
    def __init__(self, *, root, event_address: str = "0x" + "2" * 64) -> None:
        self.root = root
        self.event_address = event_address
        self.last_payload = None

    async def create_bcs_signed_transaction(self, account, payload):
        self.last_payload = payload
        return {"account": str(account.address()), "payload": payload}

    async def submit_bcs_transaction(self, signed_transaction) -> str:
        assert signed_transaction["payload"] == self.last_payload
        return "0x" + "4" * 64

    async def wait_for_transaction(self, tx_hash: str) -> None:
        assert tx_hash == "0x" + "4" * 64

    async def transaction_by_hash(self, tx_hash: str) -> dict:
        assert tx_hash == "0x" + "4" * 64
        return {
            "hash": tx_hash,
            "block_height": "456",
            "events": [
                {
                    "type": "0x3::other::Ignored",
                    "data": {"merkle_root": "f" * 64},
                },
                {
                    "type": f"{self.event_address}::merkle_registry::MerkleRootStored",
                    "data": {"merkle_root": self.root},
                },
            ],
        }


class _FakeAptosAccount:
    def __init__(self, address: str) -> None:
        self._address = address

    def address(self) -> str:
        return self._address
