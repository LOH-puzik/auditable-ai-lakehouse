"""Tests for Merkle construction and proof verification."""

from __future__ import annotations

import pytest

from swift_audit.anchoring.merkle import MerkleProof, build_tree, verify_proof
from swift_audit.hashing import sha256_hex, sha256_pair


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


def test_build_tree_round_trip() -> None:
    leaves = [sha256_hex({"leaf": index}) for index in range(4)]

    tree = build_tree(leaves)

    assert tree.leaves == leaves
    assert len(tree.proofs) == len(leaves)
    assert all(verify_proof(proof, tree.root) for proof in tree.proofs)


def test_build_tree_round_trip_with_odd_leaf_count() -> None:
    leaves = [sha256_hex({"leaf": index}) for index in range(5)]

    tree = build_tree(leaves)

    assert len(tree.proofs) == len(leaves)
    assert all(verify_proof(proof, tree.root) for proof in tree.proofs)
    assert tree.proofs[-1].siblings[0] == (leaves[-1], True)


def test_build_tree_single_leaf_has_empty_proof() -> None:
    leaf = sha256_hex({"leaf": 1})

    tree = build_tree([leaf])

    assert tree.root == leaf
    assert tree.proofs == [MerkleProof(leaf_index=0, leaf_hash=leaf, siblings=[])]


def test_build_tree_rejects_empty_leaves() -> None:
    with pytest.raises(ValueError, match="no leaves"):
        build_tree([])


def test_build_tree_rejects_invalid_leaf_hash() -> None:
    with pytest.raises(ValueError, match="64-character hex"):
        build_tree(["not-a-hash"])
