"""Unit tests for the deterministic budget optimiser (pure functions, no DB)."""

from __future__ import annotations

from uuid import uuid4

from app.core.enums import Quality
from app.domains.basket.optimizer import (
    Candidate,
    OptimizableItem,
    plan_optimization,
    total_of,
)


def _item(price: int, quality: Quality, qty: int = 1, role: str = "item", **kwargs):
    return OptimizableItem(
        item_id=uuid4(),
        role=role,
        product_id=uuid4(),
        product_name=f"product-{role}",
        unit_price=price,
        quantity=qty,
        quality=quality,
        **kwargs,
    )


def _candidate(price: int, quality: Quality) -> Candidate:
    return Candidate(product_id=uuid4(), product_name="cheaper", price=price, quality=quality)


def test_no_change_when_already_within_budget() -> None:
    items = [_item(1_000_000, Quality.MEDIUM, candidates=[_candidate(500_000, Quality.LOW)])]
    assert plan_optimization(items, 5_000_000) == []


def test_largest_saving_is_applied_first() -> None:
    tiles = _item(
        1_000,
        Quality.MEDIUM,
        qty=39,
        role="tiles",
        candidates=[_candidate(500, Quality.LOW)],
    )
    toilet = _item(
        1_000,
        Quality.MEDIUM,
        role="toilet",
        candidates=[_candidate(100, Quality.LOW)],
    )
    items = [tiles, toilet]
    original = total_of(items)

    swaps = plan_optimization(items, 10_000)

    # biggest saving first (tiles: 500 x 39) then the next best (toilet)
    assert [s.role for s in swaps] == ["tiles", "toilet"]
    assert swaps[0].saving == 500 * 39
    assert total_of(items) == original - sum(s.saving for s in swaps)
    # every item is swapped at most once
    assert len({s.item_id for s in swaps}) == len(swaps)


def test_optimization_never_increases_total() -> None:
    items = [
        _item(2_000_000, Quality.MEDIUM, role="a", candidates=[_candidate(1_500_000, Quality.LOW)]),
        _item(
            5_000_000,
            Quality.HIGH,
            qty=2,
            role="b",
            candidates=[_candidate(4_900_000, Quality.MEDIUM)],
        ),
    ]
    original = total_of(items)
    swaps = plan_optimization(items, 1_000)

    assert total_of(items) <= original
    assert all(s.saving > 0 for s in swaps)


def test_cheaper_candidate_of_same_quality_is_preferred_over_downgrade() -> None:
    item = _item(
        1_000_000,
        Quality.MEDIUM,
        role="tiles",
        candidates=[
            _candidate(900_000, Quality.LOW),  # big saving, quality loss
            _candidate(950_000, Quality.MEDIUM),  # small saving, no quality loss
        ],
    )
    swaps = plan_optimization(item_list := [item], 800_000)
    assert len(swaps) == 1
    # the biggest saving wins, but ties on saving must prefer the smaller quality loss
    assert swaps[0].to_price == 900_000
    assert total_of(item_list) == 900_000


def test_quality_floor_is_respected() -> None:
    item = _item(
        1_000_000,
        Quality.HIGH,
        role="toilet",
        quality_floor=Quality.MEDIUM,
        candidates=[
            _candidate(500_000, Quality.LOW),  # below the floor: forbidden
            _candidate(700_000, Quality.MEDIUM),  # allowed
        ],
    )
    swaps = plan_optimization([item], 100)
    assert len(swaps) == 1
    assert swaps[0].quality_to is Quality.MEDIUM


def test_locked_items_are_never_swapped() -> None:
    locked = _item(
        1_000_000,
        Quality.MEDIUM,
        role="toilet",
        locked=True,
        candidates=[_candidate(100_000, Quality.LOW)],
    )
    assert plan_optimization([locked], 1) == []


def test_more_expensive_candidate_is_never_swapped_in() -> None:
    """Cheaper is the only currency: quality never buys a higher price."""
    item = _item(
        1_000_000,
        Quality.LOW,
        role="mirror",
        candidates=[
            Candidate(
                product_id=uuid4(), product_name="premium", price=2_000_000, quality=Quality.ULTRA
            )
        ],
    )
    assert plan_optimization([item], 1) == []


def test_already_cheapest_item_is_left_alone() -> None:
    item = _item(
        1_000_000,
        Quality.MEDIUM,
        candidates=[_candidate(1_500_000, Quality.MEDIUM), _candidate(1_200_000, Quality.MEDIUM)],
    )
    assert plan_optimization([item], 1) == []


def test_budget_larger_than_total_is_a_no_op() -> None:
    item = _item(1_000_000, Quality.MEDIUM, candidates=[_candidate(500_000, Quality.LOW)])
    assert plan_optimization([item], 10_000_000) == []
