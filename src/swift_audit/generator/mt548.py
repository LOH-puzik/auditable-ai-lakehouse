"""MT548 (Settlement Status and Processing Advice) message generator.

MT548 conveys the status of a pending or settled instruction: matched, unmatched,
pending, failed, cancelled, settled. The status flow is a primary input for
settlement-fail prediction.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum


class SettlementStatus(StrEnum):
    PENDING = "PENF"
    MATCHED = "MACH"
    UNMATCHED = "NMAT"
    FAILED = "FAIL"
    SETTLED = "SETT"
    CANCELLED = "CANC"


@dataclass(frozen=True)
class MT548Message:
    transaction_reference: str  # links back to the MT540 :20C::SEME//
    status: SettlementStatus
    reason_code: str | None  # e.g. "LACK" (lack of securities), "MONY" (lack of cash)
    reported_at: datetime


_FAILURE_REASONS = ["LACK", "MONY", "CLAC", "PHYS"]


def generate_mt548_chain(
    mt540_reference: str,
    *,
    seed: int = 42,
    inject_failure: bool = False,
) -> list[MT548Message]:
    """Generate a plausible status chain for a single MT540 instruction."""
    if not mt540_reference:
        raise ValueError("mt540_reference must not be empty")

    rng = random.Random(f"{seed}:{mt540_reference}:{inject_failure}")
    reported_at = datetime(2026, 1, 2, 9, 0, tzinfo=UTC) + timedelta(
        days=rng.randrange(0, 180),
        hours=rng.randrange(0, 8),
    )

    if inject_failure:
        reason_code = rng.choice(_FAILURE_REASONS)
        return [
            MT548Message(
                transaction_reference=mt540_reference,
                status=SettlementStatus.PENDING,
                reason_code=None,
                reported_at=reported_at,
            ),
            MT548Message(
                transaction_reference=mt540_reference,
                status=SettlementStatus.UNMATCHED,
                reason_code=reason_code,
                reported_at=reported_at + timedelta(hours=rng.randrange(2, 12)),
            ),
            MT548Message(
                transaction_reference=mt540_reference,
                status=SettlementStatus.FAILED,
                reason_code=reason_code,
                reported_at=reported_at + timedelta(days=rng.randrange(1, 4)),
            ),
        ]

    matched_at = reported_at + timedelta(hours=rng.randrange(1, 12))
    settled_at = matched_at + timedelta(days=rng.choice([1, 2, 2, 3]))
    return [
        MT548Message(
            transaction_reference=mt540_reference,
            status=SettlementStatus.PENDING,
            reason_code=None,
            reported_at=reported_at,
        ),
        MT548Message(
            transaction_reference=mt540_reference,
            status=SettlementStatus.MATCHED,
            reason_code=None,
            reported_at=matched_at,
        ),
        MT548Message(
            transaction_reference=mt540_reference,
            status=SettlementStatus.SETTLED,
            reason_code=None,
            reported_at=settled_at,
        ),
    ]
