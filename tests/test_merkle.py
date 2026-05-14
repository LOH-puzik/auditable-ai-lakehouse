"""Tests for Merkle construction and proof verification."""

from __future__ import annotations

import pytest

from swift_audit.anchoring.merkle import MerkleProof, verify_proof
from swift_audit.hashing import sha256_pair


def test_verify_proof_succeeds_on_constructed_tree() -> None:
    # Hand-build a 4-leaf tree and verify the proof for leaf 0.
    leaves = ["a" * 64, "b" * 64, "c" * 64, "d" * 64]
    ab = sha256_pair(leaves[0], leaves[1])
    cd = sha256_pair(leaves[2], leaves[3])
    root = sha256_pair(ab, cd)

    proof = MerkleProof(
        leaf_index=0,
        leaf_hash=leaves[0],
        siblings=[(leaves[1], True), (cd, True)],
    )
    assert verify_proof(proof, root) is True


def test_verify_proof_fails_with_wrong_sibling() -> None:
    leaves = ["a" * 64, "b" * 64, "c" * 64, "d" * 64]
    ab = sha256_pair(leaves[0], leaves[1])
    cd = sha256_pair(leaves[2], leaves[3])
    root = sha256_pair(ab, cd)

    tampered = MerkleProof(
        leaf_index=0,
        leaf_hash=leaves[0],
        siblings=[(leaves[2], True), (cd, True)],  # wrong sibling
    )
    assert verify_proof(tampered, root) is False


@pytest.mark.skip(reason="build_tree is not yet implemented")
def test_build_tree_round_trip() -> None:
    """Once build_tree is implemented, every emitted proof must verify."""
