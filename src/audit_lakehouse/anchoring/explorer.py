"""Aptos Explorer URL helpers for live demos."""

from __future__ import annotations


def aptos_explorer_tx_url(
    tx_hash: str,
    *,
    environment: str = "testnet",
    node_url: str = "",
) -> str:
    """Build an Aptos Explorer transaction URL for the configured network."""
    if not tx_hash:
        return ""
    network = aptos_explorer_network(environment=environment, node_url=node_url)
    return f"https://explorer.aptoslabs.com/txn/{tx_hash}?network={network}"


def aptos_explorer_network(*, environment: str = "", node_url: str = "") -> str:
    """Infer the Aptos Explorer network parameter from config values."""
    haystack = f"{environment} {node_url}".lower()
    if "mainnet" in haystack:
        return "mainnet"
    if "devnet" in haystack:
        return "devnet"
    return "testnet"
