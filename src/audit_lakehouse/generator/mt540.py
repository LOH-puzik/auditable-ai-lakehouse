"""MT540 (Receive Free / Receive Against Payment) message generator.

ISO 15022 MT540 messages instruct a custodian to receive securities. Real MT540
messages have a structured block format with mandatory and optional fields; this
generator emits a simplified, schema-faithful subset sufficient for the
anomaly-detection use case.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta

_COUNTERPARTY_BICS = [
    "DEUTDEFFXXX",
    "BNPAFRPPXXX",
    "BARCGB22XXX",
    "UBSWCHZH80A",
    "INGBNL2AXXX",
    "CHASUS33XXX",
    "CITIUS33XXX",
    "SOGEFRPPXXX",
]

_CURRENCIES = ["EUR", "USD", "GBP", "CHF"]
_COUNTRY_CODES = ["US", "GB", "FR", "DE", "NL", "CH", "LU", "IE"]
_ISIN_BODY_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


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
    if n < 0:
        raise ValueError("n must be non-negative")

    rng = random.Random(seed)
    base_trade_date = date(2026, 1, 2)
    messages: list[MT540Message] = []

    for index in range(n):
        trade_date = base_trade_date + timedelta(days=rng.randrange(0, 180))
        settlement_date = trade_date + timedelta(days=rng.choice([1, 2, 2, 2, 3]))
        quantity = _generate_quantity(rng)

        is_delivery_versus_payment = rng.random() < 0.75
        currency = rng.choice(_CURRENCIES) if is_delivery_versus_payment else None
        settlement_amount = (
            round(quantity * rng.uniform(8.0, 240.0), 2) if is_delivery_versus_payment else None
        )

        messages.append(
            MT540Message(
                transaction_reference=f"SEME{seed % 10_000:04d}{index:08d}",
                isin=_generate_isin(rng),
                quantity=quantity,
                trade_date=trade_date,
                settlement_date=settlement_date,
                counterparty_bic=rng.choice(_COUNTERPARTY_BICS),
                safekeeping_account=f"SAFE{rng.randrange(0, 100_000_000):08d}",
                settlement_amount=settlement_amount,
                currency=currency,
            )
        )

    return messages


def _generate_quantity(rng: random.Random) -> float:
    base_lot = rng.choice([50, 100, 250, 500, 1_000, 2_500, 5_000])
    return round(base_lot * rng.uniform(0.8, 1.2), 2)


def _generate_isin(rng: random.Random) -> str:
    prefix = rng.choice(_COUNTRY_CODES)
    body = "".join(rng.choice(_ISIN_BODY_ALPHABET) for _ in range(9))
    partial = f"{prefix}{body}"
    return f"{partial}{_isin_check_digit(partial)}"


def _isin_check_digit(partial_isin: str) -> int:
    expanded = "".join(_expand_isin_character(character) for character in partial_isin) + "0"
    total = 0
    for position, character in enumerate(reversed(expanded)):
        digit = int(character)
        if position % 2 == 1:
            digit *= 2
            total += digit // 10 + digit % 10
        else:
            total += digit
    return (10 - total % 10) % 10


def _expand_isin_character(character: str) -> str:
    if character.isdigit():
        return character
    return str(ord(character.upper()) - 55)
