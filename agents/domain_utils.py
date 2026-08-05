from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

MONEY_QUANTUM = Decimal("0.01")


def parse_money(value: str | None, *, field: str) -> Decimal:
    if value is None:
        raise ValueError(f"{field} is missing")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field} is not a decimal: {value}") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"{field} must be finite and non-negative")
    return parsed


def money_value(value: Decimal) -> float:
    return float(value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP))


def parse_sequence(value: str | None, *, field: str) -> int:
    if value is None:
        raise ValueError(f"{field} is missing")
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{field} is not an integer: {value}") from exc
    if parsed < 1:
        raise ValueError(f"{field} must be positive")
    return parsed


def parse_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid Olist timestamp: {value}") from exc


def unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
