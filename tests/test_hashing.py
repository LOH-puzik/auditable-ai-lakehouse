"""Tests for canonical SHA-256 hashing."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from swift_audit.hashing import canonical_json, sha256_hex, sha256_pair


def test_hash_is_deterministic_across_dict_orderings() -> None:
    a = {"x": 1, "y": 2, "z": 3}
    b = {"z": 3, "y": 2, "x": 1}
    assert sha256_hex(a) == sha256_hex(b)


def test_hash_changes_with_value_change() -> None:
    a = {"x": 1, "y": 2}
    b = {"x": 1, "y": 3}
    assert sha256_hex(a) != sha256_hex(b)


def test_canonical_json_sorts_keys_and_strips_whitespace() -> None:
    assert canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'


def test_datetime_must_be_timezone_aware() -> None:
    with pytest.raises(ValueError):
        sha256_hex({"t": datetime(2026, 1, 1)})


def test_none_is_rejected() -> None:
    with pytest.raises(ValueError):
        sha256_hex({"x": None})


def test_nan_is_rejected() -> None:
    with pytest.raises(ValueError):
        sha256_hex({"x": float("nan")})


def test_utc_datetime_hashes_consistently() -> None:
    t = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    assert sha256_hex({"t": t}) == sha256_hex({"t": t})


def test_sha256_pair_is_order_sensitive() -> None:
    a = "a" * 64
    b = "b" * 64
    assert sha256_pair(a, b) != sha256_pair(b, a)
