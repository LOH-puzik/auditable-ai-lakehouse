"""Merkle tree construction and inclusion proof generation.

Given a list of leaf hashes, builds a balanced binary Merkle tree and returns
both the root and the per-leaf inclusion proofs. Odd levels are handled by
duplicating the last node (standard Bitcoin-style construction).

The output is stable and deterministic: given the same input list in the same
order, the tree and all proofs are byte-identical.
"""

from __future__ import annotations

from dataclasses import dataclass

from swift_audit.hashing import sha256_pair


@dataclass(frozen=True)
class MerkleProof:
    """An inclusion proof for a single leaf.

    The proof is a list of (sibling_hash, is_right) tuples walking from the leaf
    up to the root. To verify: start with the leaf hash; for each step, pair it
    with the sibling in the indicated order and hash; the final value must equal
    the root.
    """

    leaf_index: int
    leaf_hash: str
    siblings: list[tuple[str, bool]]  # (sibling_hash, sibling_is_right)


@dataclass(frozen=True)
class MerkleTree:
    root: str
    leaves: list[str]
    proofs: list[MerkleProof]


def build_tree(leaf_hashes: list[str]) -> MerkleTree:
    """Build a Merkle tree from a list of leaf hex digests."""
    raise NotImplementedError("Implement in step 5 of the build plan")


def verify_proof(proof: MerkleProof, expected_root: str) -> bool:
    """Verify that a proof reconstructs the expected root."""
    current = proof.leaf_hash
    for sibling, sibling_is_right in proof.siblings:
        if sibling_is_right:
            current = sha256_pair(current, sibling)
        else:
            current = sha256_pair(sibling, current)
    return current == expected_root
