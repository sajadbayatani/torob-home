"""How many of something a job needs.

A pure rule, kept out of the service so it is directly unit-testable and has no
dependency on the database or the catalogue. It used to live in the catalog
service, but it is project arithmetic and belongs to the project domain.
"""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal


def resolve_requirement_quantity(
    *,
    area_m2: float | None,
    multiplier: Decimal,
    min_qty: Decimal,
    max_qty: Decimal | None,
    quantity_mode: str,
) -> Decimal:
    """
    Deterministic quantity rule (see `ProjectRequirement`).

    Per-area requirements scale with the area and round **up**, so a small room
    still gets whole units; the result is then clamped to the requirement's own
    bounds, and never drops below one.
    """
    if quantity_mode == "per_area" and area_m2:
        raw = Decimal(str(area_m2)) * multiplier
        value = raw.quantize(Decimal("1"), rounding=ROUND_CEILING)
    else:
        value = multiplier.quantize(Decimal("1"), rounding=ROUND_CEILING)
    if value < min_qty:
        value = min_qty.quantize(Decimal("1"), rounding=ROUND_CEILING)
    if max_qty is not None and value > max_qty:
        value = max_qty.quantize(Decimal("1"), rounding=ROUND_FLOOR)
    if value < Decimal("1"):
        value = Decimal("1")
    return value


__all__ = ["resolve_requirement_quantity"]
