"""Unit tests for the shared text/number utilities and requirement quantity rules."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.text import (
    build_search_text,
    fa_number,
    format_toman,
    normalize_persian,
    numbers_in,
    tokenize,
)
from app.domains.projects.quantity import resolve_requirement_quantity


def test_normalisation_handles_persian_variants() -> None:
    # ZWNJ becomes a space and آ is folded to ا
    assert normalize_persian("می‌خواهم کاشی") == "می خواهم کاشی"
    assert normalize_persian("كاسه روشويي") == "کاسه روشویی"
    assert normalize_persian("۱۲ متر") == "12 متر"
    assert normalize_persian("قوي") == "قوی"


def test_tokenize_splits_and_deduplicates_search_text() -> None:
    assert tokenize("شیر توکار برند کاسا") == ["شیر", "توکار", "برند", "کاسا"]
    text = build_search_text("شیر توکار کاسا", "شیر توکار", "bathroom.in_wall_faucet")
    assert text == "شیر توکار کاسا bathroom in wall faucet"


def test_fa_number_uses_persian_digits_and_separators() -> None:
    assert fa_number(1234567) == "۱٬۲۳۴٬۵۶۷"
    assert fa_number(1234567.5) == "۱٬۲۳۴٬۵۶۷٫۵"
    # a whole float loses the trailing .0, which reads badly in Persian copy
    assert fa_number(12.0) == "۱۲"


def test_numbers_in_converts_persian_digits() -> None:
    assert numbers_in("۱۲ متر و ۳ عدد") == [12, 3]


def test_format_toman() -> None:
    """Backend explanations are user-facing: they must already be Persian."""
    assert format_toman(12_500_000) == "۱۲٬۵۰۰٬۰۰۰ تومان"
    assert format_toman(0) == "۰ تومان"


@pytest.mark.parametrize(
    ("area", "multiplier", "min_qty", "max_qty", "expected"),
    [
        (12, Decimal("3.2"), Decimal("10"), None, 39),  # ceil(38.4)
        (6, Decimal("3.2"), Decimal("10"), None, 20),  # ceil(19.2)
        (12, Decimal("1.25"), Decimal("5"), None, 15),  # exact
        (None, Decimal("1"), Decimal("1"), None, 1),  # fixed
        (100, Decimal("3.2"), Decimal("10"), Decimal("50"), 50),  # capped by max_qty
        (2, Decimal("3.2"), Decimal("10"), None, 10),  # raised to min_qty
    ],
)
def test_requirement_quantity_rules(area, multiplier, min_qty, max_qty, expected) -> None:
    assert (
        int(
            resolve_requirement_quantity(
                area_m2=area,
                multiplier=multiplier,
                min_qty=min_qty,
                max_qty=max_qty,
                quantity_mode="per_area" if area else "fixed",
            )
        )
        == expected
    )
