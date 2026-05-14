"""MT540 (Receive Free / Receive Against Payment) message generator.

ISO 15022 MT540 messages instruct a custodian to receive securities. Real MT540
messages have a structured block format with mandatory and optional fields; this
generator emits a simplified, schema-faithful subset sufficient for the
anomaly-detection use case.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class MT540Message:
    """A simplified MT540 record."""

    transaction_reference: str  # :20C::SEME//
    isin: str  # :35B::ISIN
    quantity: float  # :36B::SETT//
    trade_date: date  # :98A::TRAD//
    settlement_date: date  # :98A::SETT//
    counterparty_bic: str  # :95P::DEAG//
    safekeeping_account: str  # :97A::SAFE//
    settlement_amount: float | None  # :19A::SETT// (None for free-of-payment)
    currency: str | None  # ISO 4217


def generate_mt540(
    n: int,
    *,
    seed: int = 42,
) -> list[MT540Message]:
    """Generate `n` MT540 messages with deterministic seeding."""
    raise NotImplementedError("Implement in step 1 of the build plan")
