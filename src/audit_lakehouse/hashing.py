"""Canonical SHA-256 hashing.

This is the *single* source of truth for hashing across the system: ingestion,
event logging, Merkle tree construction, and replay verification all use these
helpers to ensure byte-identical inputs produce byte-identical hashes.

Canonicalization rules:
  - Dicts are serialized to JSON with sorted keys and no whitespace.
  - Floats are formatted with a fixed repr to avoid platform drift.
  - Datetimes are serialized as ISO 8601 strings in UTC.
  - Bytes are hex-encoded.
  - None / NaN are explicitly rejected (they tend to bite later).
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from typing import Any


def _canonical(value: Any) -> Any:
    """Recursively normalize a value into a canonical, JSON-serializable form."""
    if value is None:
        raise ValueError("None is not allowed in canonical hashing; use a sentinel string.")
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise ValueError(f"Non-finite float {value!r} is not allowed in canonical hashing.")
        # repr() gives the shortest round-trippable representation in Python.
        return repr(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("Naive datetime is not allowed; supply a UTC timezone.")
        return value.astimezone(UTC).isoformat()
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"Unsupported type for canonical hashing: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Return the canonical JSON string for a value (sorted keys, no whitespace)."""
    return json.dumps(_canonical(value), sort_keys=True, separators=(",", ":"))


def sha256_hex(value: Any) -> str:
    """SHA-256 hex digest of the canonical form of the given value."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_pair(left: str, right: str) -> str:
    """Hash a pair of hex digests together. Used in Merkle tree construction.

    Both inputs are decoded from hex and concatenated in their raw byte form so
    that the result is order-sensitive and independent of any string formatting.
    """
    return hashlib.sha256(bytes.fromhex(left) + bytes.fromhex(right)).hexdigest()
