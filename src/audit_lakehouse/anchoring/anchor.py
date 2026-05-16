"""Aptos anchoring adapter for Merkle roots.

The local governance event log remains the system of record. Aptos is used as an
independent append-only timestamping domain: the client calls a small Move
module that emits an event containing the 32-byte Merkle root.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from string import hexdigits
from threading import Thread
from typing import Any, TypeVar

from audit_lakehouse.anchoring.ledger import AnchorReceipt, LedgerClient

T = TypeVar("T")


class AptosLedgerClient(LedgerClient):
    """LedgerClient implementation backed by Aptos testnet/mainnet."""

    def __init__(
        self,
        node_url: str,
        private_key: str = "",
        *,
        account_address: str = "",
        module_address: str = "",
        module_name: str = "merkle_registry",
        function_name: str = "store_merkle_root",
        event_name: str = "MerkleRootStored",
        max_gas_amount: int = 10_000,
        gas_unit_price: int = 100,
        aptos_client: Any | None = None,
        aptos_account: Any | None = None,
    ) -> None:
        if not node_url:
            raise ValueError("node_url must not be empty")

        self.node_url = node_url
        self.private_key = private_key
        self.module_name = module_name
        self.function_name = function_name
        self.event_name = event_name
        self.max_gas_amount = max_gas_amount
        self.gas_unit_price = gas_unit_price
        self.account = aptos_account or (_load_account(private_key) if private_key else None)
        derived_account_address = (
            _normalize_aptos_address(str(self.account.address()))
            if self.account is not None
            else ""
        )

        if (
            account_address
            and derived_account_address
            and _canonical_aptos_address(account_address)
            != _canonical_aptos_address(derived_account_address)
        ):
            raise ValueError("account_address does not match the supplied private_key")

        self.account_address = (
            _normalize_aptos_address(account_address or derived_account_address)
            if account_address or derived_account_address
            else ""
        )
        self.module_address = (
            _normalize_aptos_address(module_address or self.account_address)
            if module_address or self.account_address
            else ""
        )
        self.client = aptos_client or _build_rest_client(
            node_url=node_url,
            max_gas_amount=max_gas_amount,
            gas_unit_price=gas_unit_price,
        )

    @property
    def event_type(self) -> str:
        """Fully qualified Move event type emitted by the anchor module."""
        if not self.module_address:
            raise ValueError("module_address is required to read an Aptos anchor event")
        return f"{self.module_address}::{self.module_name}::{self.event_name}"

    def commit_root(self, merkle_root: str) -> AnchorReceipt:
        """Submit an Aptos transaction that emits the batch Merkle root."""
        if self.account is None:
            raise ValueError("private_key is required to commit a Merkle root")
        root = _validate_merkle_root(merkle_root)
        return _run_async(self._commit_root(root))

    def read_root(self, tx_hash: str) -> str:
        """Read back the Merkle root from the anchor transaction events."""
        return _run_async(self._read_root(tx_hash))

    async def _commit_root(self, merkle_root: str) -> AnchorReceipt:
        payload = _build_anchor_payload(
            module_address=self.module_address,
            module_name=self.module_name,
            function_name=self.function_name,
            root_bytes=bytes.fromhex(merkle_root),
        )
        signed_transaction = await self.client.create_bcs_signed_transaction(self.account, payload)
        tx_hash = await self.client.submit_bcs_transaction(signed_transaction)
        await self.client.wait_for_transaction(tx_hash)
        transaction = await self.client.transaction_by_hash(tx_hash)
        anchored_root = _extract_root_from_transaction(transaction, event_type=self.event_type)
        if anchored_root != merkle_root:
            raise ValueError(
                f"Aptos root mismatch: committed {merkle_root}, read back {anchored_root}"
            )

        return AnchorReceipt(
            tx_hash=str(tx_hash),
            block_number=_extract_block_number(transaction),
            merkle_root=merkle_root,
        )

    async def _read_root(self, tx_hash: str) -> str:
        transaction = await self.client.transaction_by_hash(tx_hash)
        return _extract_root_from_transaction(transaction, event_type=self.event_type)


def _load_account(private_key: str) -> Any:
    from aptos_sdk.account import Account

    return Account.load_key(private_key)


def _build_rest_client(
    *,
    node_url: str,
    max_gas_amount: int,
    gas_unit_price: int,
) -> Any:
    from aptos_sdk.async_client import ClientConfig, RestClient

    client_config = ClientConfig(
        max_gas_amount=max_gas_amount,
        gas_unit_price=gas_unit_price,
    )
    return RestClient(node_url, client_config=client_config)


def _build_anchor_payload(
    *,
    module_address: str,
    module_name: str,
    function_name: str,
    root_bytes: bytes,
) -> Any:
    from aptos_sdk.bcs import Serializer
    from aptos_sdk.transactions import EntryFunction, TransactionArgument, TransactionPayload

    entry_function = EntryFunction.natural(
        f"{module_address}::{module_name}",
        function_name,
        [],
        [TransactionArgument(root_bytes, Serializer.to_bytes)],
    )
    return TransactionPayload(entry_function)


def _validate_merkle_root(value: str) -> str:
    root = value[2:] if value.startswith("0x") else value
    root = root.lower()
    if len(root) != 64 or any(character not in hexdigits for character in root):
        raise ValueError(f"Expected a 32-byte Merkle root hex value, got {value!r}")
    return root


def _extract_root_from_transaction(transaction: dict[str, Any], *, event_type: str) -> str:
    for event in transaction.get("events", []):
        if not isinstance(event, dict):
            continue
        if not _event_type_matches(str(event.get("type", "")), event_type):
            continue
        data = event.get("data", {})
        if isinstance(data, dict) and "merkle_root" in data:
            return _root_from_aptos_value(data["merkle_root"])

    payload = transaction.get("payload", {})
    if isinstance(payload, dict):
        arguments = payload.get("arguments", [])
        if arguments:
            return _root_from_aptos_value(arguments[0])

    raise ValueError(f"No Aptos anchor event found in transaction for {event_type}")


def _root_from_aptos_value(value: Any) -> str:
    if isinstance(value, list):
        try:
            return _validate_merkle_root(bytes(int(item) for item in value).hex())
        except ValueError as exc:
            raise ValueError(f"Invalid Aptos merkle_root vector: {value!r}") from exc

    if isinstance(value, dict) and "vec" in value:
        return _root_from_aptos_value(value["vec"])

    if isinstance(value, str):
        root = value[2:] if value.startswith("0x") else value
        return _validate_merkle_root(root)

    raise ValueError(f"Unsupported Aptos merkle_root value: {value!r}")


def _event_type_matches(actual: str, expected: str) -> bool:
    actual_parts = actual.split("::")
    expected_parts = expected.split("::")
    if len(actual_parts) != 3 or len(expected_parts) != 3:
        return False
    return (
        _canonical_aptos_address(actual_parts[0]) == _canonical_aptos_address(expected_parts[0])
        and actual_parts[1:] == expected_parts[1:]
    )


def _extract_block_number(transaction: dict[str, Any]) -> int:
    for key in ("block_height", "version"):
        value = transaction.get(key)
        if value not in (None, ""):
            return int(value)
    return 0


def _normalize_aptos_address(value: str) -> str:
    address = value.strip().lower()
    if not address:
        raise ValueError("Aptos address must not be empty")
    return address if address.startswith("0x") else f"0x{address}"


def _canonical_aptos_address(value: str) -> str:
    address = _normalize_aptos_address(value)
    body = address[2:].lstrip("0") or "0"
    return f"0x{body}"


def _run_async(coro: Coroutine[Any, Any, T]) -> T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: list[T] = []
    error: list[BaseException] = []

    def run_in_thread() -> None:
        try:
            result.append(asyncio.run(coro))
        except BaseException as exc:  # pragma: no cover - defensive bridge for notebooks.
            error.append(exc)

    thread = Thread(target=run_in_thread)
    thread.start()
    thread.join()

    if error:
        raise error[0]
    return result[0]
