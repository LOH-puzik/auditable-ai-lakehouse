"""Merkle tree construction and inclusion proof generation.

Given a list of leaf hashes, builds a balanced binary Merkle tree and returns
both the root and the per-leaf inclusion proofs. Odd levels are handled by
duplicating the last node (standard Bitcoin-style construction).

The output is stable and deterministic: given the same input list in the same
order, the tree and all proofs are byte-identical.
"""

from __future__ import annotations

from dataclasses import dataclass
from string import hexdigits

from audit_lakehouse.hashing import sha256_pair


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
    if not leaf_hashes:
        raise ValueError("Cannot build a Merkle tree with no leaves")
    for leaf_hash in leaf_hashes:
        _validate_hex_digest(leaf_hash)

    proof_steps: list[list[tuple[str, bool]]] = [[] for _ in leaf_hashes]
    level = list(leaf_hashes)
    level_indices = [[index] for index in range(len(leaf_hashes))]

    while len(level) > 1:
        next_level: list[str] = []
        next_indices: list[list[int]] = []

        for left_position in range(0, len(level), 2):
            right_position = left_position + 1
            has_right = right_position < len(level)

            left_hash = level[left_position]
            right_hash = level[right_position] if has_right else left_hash
            left_indices = level_indices[left_position]
            right_indices = level_indices[right_position] if has_right else []

            for original_index in left_indices:
                proof_steps[original_index].append((right_hash, True))
            for original_index in right_indices:
                proof_steps[original_index].append((left_hash, False))

            next_level.append(sha256_pair(left_hash, right_hash))
            next_indices.append(left_indices + right_indices)

        level = next_level
        level_indices = next_indices

    return MerkleTree(
        root=level[0],
        leaves=list(leaf_hashes),
        proofs=[
            MerkleProof(
                leaf_index=index,
                leaf_hash=leaf_hash,
                siblings=proof_steps[index],
            )
            for index, leaf_hash in enumerate(leaf_hashes)
        ],
    )


def _validate_hex_digest(value: str) -> None:
    if len(value) != 64 or any(character not in hexdigits for character in value):
        raise ValueError(f"Expected a 64-character hex digest, got {value!r}")


def verify_proof(proof: MerkleProof, expected_root: str) -> bool:
    """Verify that a proof reconstructs the expected root."""
    current = proof.leaf_hash
    for sibling, sibling_is_right in proof.siblings:
        if sibling_is_right:
            current = sha256_pair(current, sibling)
        else:
            current = sha256_pair(sibling, current)
    return current == expected_root
